"""자체 홈페이지 게시판 발행 — 오케스트레이터.

워드프레스 발행(publish.py)과 같은 플래너, 같은 게이트를 쓰되 발행처만 다릅니다.

    같은 것    진행 상황 = 컨펌 진행 중 · 제목 · 원고 · 발행 예정일 ≤ 오늘 ·
              썸네일 · 본문 이미지 · 메타타이틀 · 메타디스크립션
    다른 것    슬러그가 없어도 됨 (글 번호로 주소가 정해짐)
              Rank Math · 스키마 · 카테고리 없음
              중복 방지는 노션 ID 각인이 아니라 게시판 목록의 제목 대조
              조회수를 임의 값(프로파일의 범위)으로 채움 — 팀의 관행

발행이 끝나면 워드프레스와 똑같이 플래너를 '게재완료'로 바꾸고 URL 을 씁니다.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import notion_api as napi
from .board import BoardClient, BoardError, BoardPost, BoardProfile
from .boardhtml import render
from .config import Config, Secrets, board_credentials
from .gutenberg import image_block
from .images import Placement
from .notion_api import NotionClient
from .publish import (
    Candidate,
    Outcome,
    body_image_sources,
    iter_candidates,
    load_plan,
    mark_error,
    prepare_page,
    skipped_outcome,
    thumbnail_source,
    today_kst,
    uses_hero_image,
)
from .runlog import RunLogger

log = logging.getLogger(__name__)

STAGE = "게시판 발행"


@dataclass
class BoardPublisher:
    """한 고객사의 자체 게시판에 발행합니다.

    브라우저는 발행할 원고가 실제로 있을 때만 띄웁니다. 대상이 0건인 날이 대부분인데
    그때마다 관리자에 로그인할 이유가 없습니다.
    """

    cfg: Config
    secrets: Secrets | None = None
    dry_run: bool = False
    plan_root: Path | None = None
    notion: Any = None
    #: 테스트에서 가짜 드라이버를 꽂는 자리. (profile, user, password) → 컨텍스트 매니저
    client_factory: Any = None
    profile: BoardProfile | None = None
    artifacts: Path = field(default_factory=lambda: Path("work") / "board")

    def __post_init__(self) -> None:
        if self.notion is None:
            if self.secrets is None:
                raise ValueError("secrets 없이 만들려면 notion 클라이언트를 넘겨야 합니다.")
            self.notion = NotionClient(self.secrets.notion_token, self.cfg.notion)
        if self.profile is None:
            self.profile = BoardProfile.load(self.cfg.board.admin_url)
        # 같은 로그 DB 에 워드프레스 발행 로그와 함께 쌓이므로 단계 이름으로 구분합니다.
        self.runlog = RunLogger(replace(self.cfg.run_log, stage=STAGE), self.cfg.client, self.notion)

    # -------------------------------------------------------------------- 실행

    def run(self) -> list[Outcome]:
        started = time.monotonic()
        on = today_kst()
        log.info("기준 날짜 %s (Asia/Seoul) · 게시판 발행 · %s", on, self.cfg.client)

        outcomes: list[Outcome] = []
        ready: list[Candidate] = []
        for cand in iter_candidates(self.cfg, self.notion, on=on, require_slug=False):
            if cand.ok:
                ready.append(cand)
            else:
                outcomes.append(skipped_outcome(cand))

        if ready and self.dry_run:
            for cand in ready:
                out = Outcome(page_id=cand.page_id, title=cand.title, skipped=True)
                out.reasons = ["dry-run — 실제 발행하지 않음"]
                outcomes.append(out)
        elif ready:
            outcomes.extend(self._publish_all(ready))

        if not self.dry_run:
            self.runlog.write(outcomes, duration_min=(time.monotonic() - started) / 60)
        return outcomes

    def prepare(self, root: Path) -> list[Outcome]:
        """이미지를 내려받고 plan.json 을 만듭니다. 워드프레스 준비 단계와 같습니다."""
        on = today_kst()
        outcomes: list[Outcome] = []
        for cand in iter_candidates(self.cfg, self.notion, on=on, require_slug=False):
            if not cand.ok:
                outcomes.append(skipped_outcome(cand))
                continue
            try:
                outcomes.append(prepare_page(self.cfg, cand, root))
            except Exception as exc:
                log.error("준비 실패 [%s] %s", cand.title[:40], exc)
                outcomes.append(Outcome(page_id=cand.page_id, title=cand.title, error=str(exc)))

        if not any(o.prepared for o in outcomes):
            self.runlog.write(outcomes, note="준비 단계에서 발행 대상 없음")
        return outcomes

    # ------------------------------------------------------------ 브라우저 세션

    def _open_client(self) -> Any:
        assert self.profile is not None
        user, password = board_credentials(self.cfg.board.admin_url)
        factory = self.client_factory or (
            lambda profile, u, p: BoardClient(profile, u, p, artifacts=self.artifacts)
        )
        return factory(self.profile, user, password)

    def _publish_all(self, ready: list[Candidate]) -> list[Outcome]:
        outcomes: list[Outcome] = []
        try:
            with self._open_client() as client:
                client.login()
                for cand in ready:
                    outcomes.append(self._publish(cand, client))
        except Exception as exc:
            # 로그인 자체가 안 되면 모든 후보가 같은 이유로 실패한 것입니다.
            # 원고 탓이 아니므로 플래너 상태는 건드리지 않습니다.
            log.error("게시판에 들어가지 못했습니다: %s", exc)
            done = {o.page_id for o in outcomes}
            for cand in ready:
                if cand.page_id not in done:
                    outcomes.append(Outcome(page_id=cand.page_id, title=cand.title, error=str(exc)))
        return outcomes

    # ------------------------------------------------------------------ 단건 발행

    def _publish(self, cand: Candidate, client: Any) -> Outcome:
        nc = self.cfg.notion
        out = Outcome(page_id=cand.page_id, title=cand.title)
        assert cand.extracted is not None
        assert self.profile is not None

        def prop(key: str) -> dict[str, Any] | None:
            return cand.props.get(nc.prop(key))

        title = cand.title.strip()
        slug = napi.read_text(prop("slug")).strip() or f"post-{cand.page_id.replace('-', '')[:8]}"
        meta_title = napi.read_text(prop("meta_title")).strip()
        meta_desc = napi.read_text(prop("meta_description")).strip()

        try:
            # 1) 이미 올라가 있는가. 제목이 열쇠입니다 — 지난 회차에 등록까지 되고
            #    노션 되돌려 쓰기만 실패했을 때 여기서 잡힙니다.
            existing = client.find_post(title)
            if existing is not None:
                log.info("이미 게시판에 있음: %s", title[:40])
                out.skipped = True
                out.reasons = ["이미 게시판에 같은 제목의 글이 있음"]
                out.link = existing.link
                self._write_back(cand.page_id, existing)
                return out

            # 2) 이미지 준비. plan.json 이 있으면 검수된 ALT 를, 없으면 원고의 가이드를 씁니다.
            plan = load_plan(self.plan_root, cand.page_id)
            thumb_name, thumb_bytes, thumb_alt = thumbnail_source(
                prop("thumbnail"), plan, self.plan_root, slug, meta_title or title
            )
            sources = body_image_sources(prop("body_images"), plan, self.plan_root, cand, slug)

            uploads: list[tuple[str, bytes]] = []
            placements: list[Placement] = []
            if uses_hero_image(self.cfg, cand.props):
                # 숏폼: 썸네일 한 장이 본문 맨 위 사진입니다.
                uploads.append((thumb_name, thumb_bytes))
                placements.append(Placement(index=0, alt=thumb_alt))
            for name, data, placement in sources:
                uploads.append((name, data))
                placements.append(placement)

            body = list(cand.extracted.body)

            def compose(urls: list[str]) -> str:
                merged = list(body)
                for offset, (placement, url) in enumerate(zip(placements, urls, strict=True)):
                    merged.insert(
                        placement.index + offset,
                        image_block(url=url, media_id=0, alt=placement.alt),
                    )
                return render(merged, title=title, meta_title=meta_title, meta_description=meta_desc)

            # 3) 조회수는 팀이 손으로 올릴 때처럼 범위 안의 임의 값입니다.
            hit = random.randint(self.profile.hit_min, self.profile.hit_max)

            post = client.publish(title=title, hit=hit, images=uploads, compose=compose)
            out.published = True
            out.link = post.link
            if not post.id:
                out.warnings.append("글은 올라갔지만 목록에서 글 번호를 읽지 못해 URL 을 비워 두었습니다")

            # 4) 노션 되돌려 쓰기.
            self._write_back(cand.page_id, post)
            log.info("게시판 발행 완료: %s → %s", title[:40], post.link or "(주소 없음)")
            return out

        except Exception as exc:
            out.error = str(exc)
            log.error("게시판 발행 실패 [%s] %s", title[:40], exc)
            if not self.dry_run:
                mark_error(self.cfg, self.notion, cand.page_id)
            return out

    def _write_back(self, page_id: str, post: BoardPost) -> None:
        nc = self.cfg.notion
        props: dict[str, Any] = {nc.prop("status"): napi.write_status(nc.status_done)}
        if post.link:
            props[nc.prop("url")] = napi.write_url(post.link)
        self.notion.update_page(page_id, props)


__all__ = ["STAGE", "BoardError", "BoardPublisher"]
