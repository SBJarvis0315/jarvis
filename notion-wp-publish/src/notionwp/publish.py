"""발행 게이트와 오케스트레이터.

게이트(요구사항 2번)는 아래를 전부 만족해야 통과합니다. 하나라도 빠지면 발행하지 않습니다.
    · 진행 상황 = 컨펌 진행 중
    · 제목에 텍스트가 있을 것
    · 페이지 안에 원고가 있을 것 (콘텐츠 가이드 토글·검수용 섹션 제외하고도 내용이 남을 것)
    · 발행 예정일이 기재되어 있고, 오늘 이하일 것
    · 썸네일 · 본문 이미지 · 메타타이틀 · 메타디스크립션 · 슬러그가 모두 기재되어 있을 것

발행 순서는 '초안 생성 → 노션 ID 각인 → SEO 기입 → 공개' 입니다.
중간에 실패해도 공개되지 않고, 각인된 ID 덕분에 다음 회차에서 중복 발행이 나지 않습니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import notion_api as napi
from .config import Config, Secrets
from .extract import Extracted, extract
from .gutenberg import RenderOptions, image_block, render
from .images import Placement, iter_files, plan_placements, target_filename
from .notion_api import NotionClient
from .schema import build_schemas
from .wordpress import WordPressClient, WordPressError, download

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


@dataclass
class Candidate:
    page_id: str
    title: str
    props: dict[str, Any]
    reasons: list[str] = field(default_factory=list)
    extracted: Extracted | None = None

    @property
    def ok(self) -> bool:
        return not self.reasons


@dataclass
class Outcome:
    page_id: str
    title: str
    published: bool = False
    skipped: bool = False
    link: str = ""
    post_id: int | None = None
    reasons: list[str] = field(default_factory=list)
    error: str = ""


def today_kst() -> date:
    return datetime.now(KST).date()


# ------------------------------------------------------------------------ 게이트


def check_properties(cfg: Config, page: dict[str, Any], *, on: date) -> Candidate:
    """블록을 내려받기 전에, 속성만으로 판별할 수 있는 조건을 먼저 봅니다."""
    nc = cfg.notion
    props = page.get("properties") or {}

    def prop(key: str) -> dict[str, Any] | None:
        return props.get(nc.prop(key))

    title = napi.read_text(prop("title"))
    cand = Candidate(page_id=page["id"], title=title, props=props)

    status = napi.read_select(prop("status"))
    if status != nc.status_ready:
        cand.reasons.append(f"진행 상황이 '{nc.status_ready}'가 아님 (현재: {status or '비어 있음'})")

    if nc.type_filter:
        kind = napi.read_select(prop("type"))
        if kind not in nc.type_filter:
            cand.reasons.append(f"유형이 대상이 아님 (현재: {kind or '비어 있음'})")

    if not title.strip():
        cand.reasons.append("제목이 비어 있음")

    raw_date = napi.read_date(prop("publish_date"))
    if not raw_date:
        cand.reasons.append("발행 예정일이 비어 있음")
    else:
        try:
            scheduled = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
        except ValueError:
            cand.reasons.append(f"발행 예정일을 읽을 수 없음: {raw_date}")
        else:
            if scheduled > on:
                cand.reasons.append(f"발행 예정일이 아직 오지 않음 ({scheduled} > {on})")

    if not iter_files(prop("thumbnail")):
        cand.reasons.append("썸네일이 비어 있음")
    if not iter_files(prop("body_images")):
        cand.reasons.append("본문 이미지가 비어 있음")

    for key, label in (
        ("meta_title", "메타타이틀"),
        ("meta_description", "메타디스크립션"),
        ("slug", "슬러그"),
    ):
        if not napi.read_text(prop(key)).strip():
            cand.reasons.append(f"{label}이(가) 비어 있음")

    return cand


def check_body(cand: Candidate, blocks: list[dict[str, Any]]) -> Candidate:
    """원고 본문이 실제로 있는지 확인합니다."""
    cand.extracted = extract(blocks)
    if cand.extracted.is_empty:
        cand.reasons.append("페이지에 발행할 원고가 없음 (콘텐츠 가이드·검수용 섹션 제외 후 비어 있음)")
    return cand


# ------------------------------------------------------------------ 오케스트레이터


class Publisher:
    def __init__(
        self,
        cfg: Config,
        secrets: Secrets | None = None,
        *,
        dry_run: bool = False,
        notion: NotionClient | None = None,
        wp: WordPressClient | None = None,
    ):
        if secrets is None and (notion is None or wp is None):
            raise ValueError("secrets 없이 만들려면 notion·wp 클라이언트를 모두 넘겨야 합니다.")

        self.cfg = cfg
        self.dry_run = dry_run
        self.notion = notion or NotionClient(secrets.notion_token, cfg.notion)  # type: ignore[union-attr]
        self.wp = wp or WordPressClient(
            cfg.wordpress,
            secrets.wp_user,  # type: ignore[union-attr]
            secrets.wp_app_password,  # type: ignore[union-attr]
        )

    # -------------------------------------------------------------------- 실행

    def run(self) -> list[Outcome]:
        self.wp.bridge_ping()

        on = today_kst()
        log.info("기준 날짜 %s (Asia/Seoul) · 대상 플래너 %s", on, self.cfg.client)

        outcomes: list[Outcome] = []
        for page in self.notion.query_planner():
            cand = check_properties(self.cfg, page, on=on)

            if not cand.ok:
                log.debug("건너뜀 [%s] %s", cand.title[:30], "; ".join(cand.reasons))
                outcomes.append(
                    Outcome(
                        page_id=cand.page_id,
                        title=cand.title,
                        skipped=True,
                        reasons=cand.reasons,
                    )
                )
                continue

            blocks = self.notion.fetch_blocks(cand.page_id)
            cand = check_body(cand, blocks)

            if not cand.ok:
                log.info("건너뜀 [%s] %s", cand.title[:30], "; ".join(cand.reasons))
                outcomes.append(
                    Outcome(
                        page_id=cand.page_id,
                        title=cand.title,
                        skipped=True,
                        reasons=cand.reasons,
                    )
                )
                continue

            outcomes.append(self._publish(cand))

        return outcomes

    # ------------------------------------------------------------------ 단건 발행

    def _publish(self, cand: Candidate) -> Outcome:
        nc = self.cfg.notion
        out = Outcome(page_id=cand.page_id, title=cand.title)

        def prop(key: str) -> dict[str, Any] | None:
            return cand.props.get(nc.prop(key))

        slug = napi.read_text(prop("slug")).strip()
        meta_title = napi.read_text(prop("meta_title")).strip()
        meta_desc = napi.read_text(prop("meta_description")).strip()
        keywords = napi.read_text(prop("keywords")).strip()
        category = napi.read_select(prop("category"))

        try:
            # 1) 이미 발행된 적이 있는지 — 하루 두 번 도는 구조라 중복 방지가 필수입니다.
            existing = self.wp.lookup_by_notion_id(cand.page_id)
            post_id: int | None = None

            if existing.get("found"):
                if existing.get("status") == "publish":
                    log.info("이미 발행됨, 건너뜀: %s", cand.title[:40])
                    out.skipped = True
                    out.reasons = ["이미 발행된 원고 (워드프레스에 노션 페이지 ID가 남아 있음)"]
                    out.link = existing.get("link", "")
                    out.post_id = existing.get("post_id")
                    return out
                # 지난 회차에 초안까지만 만들어졌다면 이어서 진행합니다.
                post_id = int(existing["post_id"])
                log.info("남아 있는 초안을 이어서 발행합니다 (post %s)", post_id)

            if self.dry_run:
                out.reasons = ["dry-run — 실제 발행하지 않음"]
                out.skipped = True
                return out

            # 2) 이미지 업로드. 노션 URL은 1시간 뒤 만료되므로 지금 내려받아 재업로드합니다.
            thumb_files = iter_files(prop("thumbnail"))
            body_files = iter_files(prop("body_images"))
            assert cand.extracted is not None

            placements = plan_placements(
                cand.extracted.body,
                cand.extracted.image_hints,
                image_count=len(body_files),
                fallback_alt_prefix=cand.title,
            )

            thumb = self.wp.upload_media(
                target_filename(slug, None, thumb_files[0].url, thumb_files[0].name),
                download(thumb_files[0].url),
                alt=meta_title or cand.title,
            )

            body = list(cand.extracted.body)
            uploaded: list[tuple[Placement, int, str]] = []
            for n, (file, placement) in enumerate(
                zip(body_files, placements, strict=True), start=1
            ):
                media = self.wp.upload_media(
                    target_filename(slug, n, file.url, file.name),
                    download(file.url),
                    alt=placement.alt,
                )
                uploaded.append((placement, media.id, media.url))

            for offset, (placement, media_id, media_url) in enumerate(uploaded):
                body.insert(
                    placement.index + offset,
                    image_block(url=media_url, media_id=media_id, alt=placement.alt),
                )

            content = render(
                body,
                RenderOptions(
                    spacer_height=self.cfg.render.spacer_height,
                    spacer_before_headings=self.cfg.render.spacer_before_headings,
                    center_tables=self.cfg.render.center_tables,
                ),
            )

            # 3) 슬러그 충돌 확인. 방치하면 워드프레스가 말없이 -2 를 붙입니다.
            if post_id is None and self.wp.slug_taken(slug):
                raise WordPressError(
                    f"슬러그 '{slug}' 가 이미 사용 중입니다. 플래너에서 슬러그를 바꿔 주세요."
                )

            category_name = self.cfg.wordpress.category_map.get(
                category, category or self.cfg.wordpress.default_category
            )
            category_ids = [
                cid for cid in [self.wp.resolve_category(category_name)] if cid is not None
            ]

            # 4) 먼저 초안으로 만듭니다. SEO 기입까지 끝난 뒤에 공개합니다.
            if post_id is None:
                post = self.wp.create_post(
                    title=cand.title,
                    content=content,
                    slug=slug,
                    status="draft",
                    categories=category_ids,
                    featured_media=thumb.id,
                )
                post_id = post.id
                out.post_id = post_id

                # 노션 페이지 ID를 곧바로 각인해 둡니다. 이후 단계가 실패해도
                # 다음 회차가 이 초안을 찾아내 이어서 진행합니다.
                self.wp.apply_seo(post_id, {"notion_page_id": cand.page_id})
            else:
                out.post_id = post_id
                self.wp.update_post(
                    post_id,
                    {
                        "title": cand.title,
                        "content": content,
                        "slug": slug,
                        "categories": category_ids,
                        "featured_media": thumb.id,
                    },
                )

            guessed_permalink = f"{self.cfg.wordpress.base_url.rstrip('/')}/{slug}/"
            published_iso = datetime.now(KST).isoformat(timespec="seconds")

            def seo_payload(permalink: str) -> dict[str, Any]:
                return {
                    "notion_page_id": cand.page_id,
                    "rank_math_title": meta_title,
                    "rank_math_description": meta_desc,
                    "rank_math_focus_keyword": keywords,
                    "schema_mode": self.cfg.wordpress.schema_mode,
                    "schemas": build_schemas(
                        body=cand.extracted.body,  # type: ignore[union-attr]
                        headline=meta_title or cand.title,
                        description=meta_desc,
                        permalink=permalink,
                        published_iso=published_iso,
                        image_url=thumb.url,
                        keywords=keywords,
                        publisher_name=self.cfg.wordpress.publisher_name,
                        publisher_logo=self.cfg.wordpress.publisher_logo,
                        author_name=self.cfg.wordpress.author_name,
                    ),
                }

            # 5) Rank Math — 가이드 ⑤ 에 해당하는 부분. 공개 전에 채워둡니다.
            self.wp.apply_seo(post_id, seo_payload(guessed_permalink))

            # 6) 공개.
            published = self.wp.update_post(post_id, {"status": "publish"})
            out.link = published.link or guessed_permalink
            out.published = True

            # 6b) 고유주소 설정에 따라 실제 주소가 추측과 다를 수 있습니다.
            #     그 경우 스키마의 @id·url 이 어긋나므로 진짜 주소로 다시 써줍니다.
            #     (mu-plugin 이 매번 기존 스키마를 비우고 다시 쓰므로 중복되지 않습니다.)
            if out.link and out.link.rstrip("/") != guessed_permalink.rstrip("/"):
                log.info("고유주소가 예상과 달라 스키마를 실제 주소로 보정합니다: %s", out.link)
                self.wp.apply_seo(post_id, seo_payload(out.link))

            # 7) 노션 되돌려 쓰기 (요구사항 3번).
            self.notion.update_page(
                cand.page_id,
                {
                    nc.prop("status"): napi.write_status(nc.status_done),
                    nc.prop("url"): napi.write_url(out.link),
                },
            )

            log.info("발행 완료: %s → %s", cand.title[:40], out.link)
            return out

        except Exception as exc:
            out.error = str(exc)
            log.error("발행 실패 [%s] %s", cand.title[:40], exc)
            self._mark_error(cand.page_id)
            return out

    def _mark_error(self, page_id: str) -> None:
        """실패한 행을 '발행 오류'로 표시합니다. 상태 옵션이 없으면 조용히 넘어갑니다."""
        if self.dry_run or not self.cfg.notion.status_error:
            return
        try:
            self.notion.update_page(
                page_id,
                {self.cfg.notion.prop("status"): napi.write_status(self.cfg.notion.status_error)},
            )
        except Exception as exc:
            log.warning(
                "'%s' 상태로 바꾸지 못했습니다. 플래너 진행 상황에 해당 옵션이 있는지 확인해 주세요: %s",
                self.cfg.notion.status_error,
                exc,
            )


def summarize(outcomes: list[Outcome]) -> str:
    published = [o for o in outcomes if o.published]
    failed = [o for o in outcomes if o.error]
    skipped = [o for o in outcomes if o.skipped]

    lines = [
        f"발행 {len(published)}건 · 실패 {len(failed)}건 · 대기/제외 {len(skipped)}건",
        "",
    ]

    for o in published:
        lines.append(f"  ✅ {o.title[:50]}\n     {o.link}")
    for o in failed:
        lines.append(f"  ❌ {o.title[:50]}\n     {o.error}")

    # 발행 직전까지 갔다가 걸린 것만 보여줍니다. 아직 작성 중인 행까지 나열하면
    # 로그가 길어져서 정작 봐야 할 것이 묻힙니다.
    near_miss = [
        o
        for o in skipped
        if o.reasons and not any("진행 상황이" in r or "유형이" in r for r in o.reasons)
    ]
    for o in near_miss:
        lines.append(f"  ⏸ {o.title[:50]}\n     {'; '.join(o.reasons)}")

    return "\n".join(lines)
