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
import posixpath
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from . import notion_api as napi
from .config import Config, Secrets
from .extract import Extracted, extract
from .gutenberg import RenderOptions, image_block, render
from .images import (
    Placement,
    iter_files,
    plan_placements,
    spread_evenly,
    target_filename,
)
from .notion_api import NotionClient
from .plan import (
    PLAN_FILENAME,
    PagePlan,
    PlannedImage,
    make_preview,
    outline,
    plan_dir_for,
)
from .runlog import RunLogger
from .schema import build_schemas
from .wordpress import WordPressClient, WordPressError, download


def _suffix(url: str, name: str = "") -> str:
    """원본 파일의 확장자를 그대로 살립니다 (없으면 .jpg)."""
    for value in (url, name):
        if not value:
            continue
        path = urlparse(value).path if "://" in value else value
        ext = posixpath.splitext(unquote(path))[1].lower()
        if re.fullmatch(r"\.[a-z0-9]{2,5}", ext or ""):
            return ext
    return ".jpg"

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
    #: --draft 로 돌려 임시저장까지만 한 경우. 공개되지 않았고 노션도 건드리지 않았습니다.
    drafted: bool = False
    edit_link: str = ""
    #: --prepare 로 이미지 내려받기와 plan.json 생성까지만 한 경우.
    prepared: bool = False
    plan_path: str = ""


def today_kst() -> date:
    return datetime.now(KST).date()


# ------------------------------------------------------------------------ 게이트


def uses_hero_image(cfg: Config, props: dict[str, Any]) -> bool:
    """썸네일을 본문 맨 위에도 넣는 유형인가.

    숏폼처럼 사진이 한 장뿐인 글에서 쓰입니다. 이 유형은 썸네일만 올리면 되고,
    같은 미디어를 재사용하므로 워드프레스에 같은 파일이 두 번 올라가지 않습니다.
    """
    types = cfg.render.hero_image_types
    if not types:
        return False
    return napi.read_select((props or {}).get(cfg.notion.prop("type"))) in types


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
    if not iter_files(prop("body_images")) and not uses_hero_image(cfg, props):
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
        draft: bool = False,
        plan_root: Path | None = None,
        notion: NotionClient | None = None,
        wp: WordPressClient | None = None,
    ):
        if secrets is None and (notion is None or wp is None):
            raise ValueError("secrets 없이 만들려면 notion·wp 클라이언트를 모두 넘겨야 합니다.")

        self.cfg = cfg
        self.dry_run = dry_run
        # 임시저장 모드: 워드프레스에 초안까지 만들고 Rank Math 까지 채우되
        # 공개하지 않고, 노션 상태도 건드리지 않습니다.
        self.draft = draft
        # plan.json 이 있는 작업 폴더. 있으면 검수된 ALT·배치를 그대로 씁니다.
        self.plan_root = plan_root
        self.notion = notion or NotionClient(secrets.notion_token, cfg.notion)  # type: ignore[union-attr]
        self.wp = wp or WordPressClient(
            cfg.wordpress,
            secrets.wp_user,  # type: ignore[union-attr]
            secrets.wp_app_password,  # type: ignore[union-attr]
        )
        self.runlog = RunLogger(cfg.run_log, cfg.client, self.notion)

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

        # --dry-run 은 아무것도 하지 않았고, --draft 는 공개하지도 노션을 건드리지도
        # 않았으므로 운영 로그에 남기지 않습니다.
        if not self.dry_run and not self.draft:
            self.runlog.write(outcomes)

        return outcomes

    # -------------------------------------------------------------------- 준비

    def prepare(self, root: Path) -> list[Outcome]:
        """발행 대상 원고의 이미지를 내려받고 plan.json 을 만듭니다.

        스크립트는 이미지를 볼 수 없으므로, 여기까지만 하고 ALT 는 비워 둡니다.
        이어서 사람이나 루틴 안의 Claude 가 이미지를 보고 채웁니다.
        """
        on = today_kst()
        log.info("준비 · 기준 날짜 %s (Asia/Seoul) · %s", on, self.cfg.client)

        outcomes: list[Outcome] = []
        for page in self.notion.query_planner():
            cand = check_properties(self.cfg, page, on=on)
            if not cand.ok:
                outcomes.append(
                    Outcome(page_id=cand.page_id, title=cand.title, skipped=True, reasons=cand.reasons)
                )
                continue

            cand = check_body(cand, self.notion.fetch_blocks(cand.page_id))
            if not cand.ok:
                outcomes.append(
                    Outcome(page_id=cand.page_id, title=cand.title, skipped=True, reasons=cand.reasons)
                )
                continue

            try:
                outcomes.append(self._prepare_one(cand, root))
            except Exception as exc:
                log.error("준비 실패 [%s] %s", cand.title[:40], exc)
                outcomes.append(
                    Outcome(page_id=cand.page_id, title=cand.title, error=str(exc))
                )

        # 준비 단계는 보통 뒤이어 --plan 이 돌면서 로그를 남깁니다. 다만 대상이 0건이면
        # --plan 을 돌릴 일이 없어 그날 기록이 통째로 비므로, 그 경우만 여기서 남깁니다.
        if not any(o.prepared for o in outcomes):
            self.runlog.write(outcomes, note="준비 단계에서 발행 대상 없음")

        return outcomes

    def _prepare_one(self, cand: Candidate, root: Path) -> Outcome:
        nc = self.cfg.notion
        assert cand.extracted is not None

        def prop(key: str) -> dict[str, Any] | None:
            return cand.props.get(nc.prop(key))

        slug = napi.read_text(prop("slug")).strip()
        directory = plan_dir_for(root, cand.page_id)
        (directory / "images").mkdir(parents=True, exist_ok=True)

        body_files = iter_files(prop("body_images"))
        thumb_files = iter_files(prop("thumbnail"))

        # 원고에 `::IMG-01::` 마커가 있으면 글쓴이가 정한 그 자리를 씁니다.
        # 없으면 H2/H3 구간에 고르게 배분합니다.
        body_markers = [m for m in cand.extracted.markers if not m.is_thumbnail]
        if body_markers:
            ordered = sorted(body_markers, key=lambda m: (m.number or 0, m.index))
            anchors = [m.index for m in ordered]
            hints = [m.alt_hint or m.note for m in ordered]
            log.info("본문 마커 %d개를 배치 기준으로 씁니다", len(anchors))
        else:
            anchors = spread_evenly(cand.extracted.body, len(body_files))
            hints = []

        page_plan = PagePlan(
            page_id=cand.page_id,
            title=cand.title,
            slug=slug,
            sections=outline(cand.extracted.body),
        )

        # 썸네일
        thumb_path = Path("images") / f"thumbnail{_suffix(thumb_files[0].url, thumb_files[0].name)}"
        (directory / thumb_path).write_bytes(download(thumb_files[0].url))
        page_plan.thumbnail = str(thumb_path)
        thumb_marker = next((m for m in cand.extracted.markers if m.is_thumbnail), None)
        if thumb_marker:
            page_plan.thumbnail_hint = thumb_marker.alt_hint or thumb_marker.note
        preview = Path("images") / "thumbnail-preview.jpg"
        if make_preview(directory / thumb_path, directory / preview):
            page_plan.thumbnail_preview = str(preview)

        # 본문 이미지
        for n, file in enumerate(body_files, start=1):
            original = Path("images") / f"{n}{_suffix(file.url, file.name)}"
            (directory / original).write_bytes(download(file.url))

            preview = Path("images") / f"{n}-preview.jpg"
            has_preview = make_preview(directory / original, directory / preview)

            page_plan.images.append(
                PlannedImage(
                    n=n,
                    original=str(original),
                    preview=str(preview) if has_preview else str(original),
                    anchor=anchors[n - 1] if n - 1 < len(anchors) else len(cand.extracted.body),
                    alt="",
                    source_name=file.name,
                    hint=hints[n - 1] if n - 1 < len(hints) else "",
                )
            )

        path = page_plan.save(directory)
        log.info("준비 완료: %s → %s (이미지 %d장)", cand.title[:40], path, len(body_files))

        return Outcome(
            page_id=cand.page_id,
            title=cand.title,
            prepared=True,
            plan_path=str(path),
        )

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
                log.info(
                    "남아 있는 초안을 %s (post %s)",
                    "다시 씁니다" if self.draft else "이어서 발행합니다",
                    post_id,
                )

            if self.dry_run:
                out.reasons = ["dry-run — 실제 발행하지 않음"]
                out.skipped = True
                return out

            # 2) 이미지 업로드.
            #    plan.json 이 있으면 미리 내려받아둔 파일과 사람이 검수한 ALT를 씁니다.
            #    없으면 지금 노션에서 내려받고 원고의 ALT 가이드를 폴백으로 씁니다.
            assert cand.extracted is not None
            page_plan = self._load_plan(cand.page_id)

            thumb_name, thumb_bytes, thumb_alt = self._thumbnail_source(
                prop("thumbnail"), page_plan, slug, meta_title or cand.title
            )
            thumb = self.wp.upload_media(thumb_name, thumb_bytes, alt=thumb_alt)

            body = list(cand.extracted.body)
            uploaded: list[tuple[Placement, int, str]] = []

            for n, (name, data, placement) in enumerate(
                self._body_image_sources(prop("body_images"), page_plan, cand, slug), start=1
            ):
                media = self.wp.upload_media(name, data, alt=placement.alt)
                uploaded.append((placement, media.id, media.url))
                log.debug("이미지 %d → %s (%s)", n, media.url, placement.alt[:30])

            if uses_hero_image(self.cfg, cand.props):
                uploaded.insert(0, (Placement(index=0, alt=thumb_alt), thumb.id, thumb.url))
                log.info("썸네일을 본문 맨 위에 재사용합니다 (재업로드 없음)")

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

            out.edit_link = (
                f"{self.cfg.wordpress.base_url.rstrip('/')}"
                f"/wp-admin/post.php?post={post_id}&action=edit"
            )

            # 임시저장 모드는 여기서 멈춥니다.
            # 글은 초안으로 남고, 노션 상태도 '컨펌 진행 중' 그대로 둡니다.
            if self.draft:
                out.drafted = True
                out.link = guessed_permalink
                log.info("임시저장 완료(비공개): %s → %s", cand.title[:40], out.edit_link)
                return out

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

    # ------------------------------------------------------- 이미지 출처 결정

    def _load_plan(self, page_id: str) -> PagePlan | None:
        if not self.plan_root:
            return None
        directory = plan_dir_for(self.plan_root, page_id)
        if not (directory / PLAN_FILENAME).exists():
            log.warning("plan.json 이 없어 원고의 ALT 가이드로 진행합니다: %s", directory)
            return None

        plan = PagePlan.load(directory)
        if plan.missing_alts:
            raise WordPressError(
                f"plan.json 의 ALT가 비어 있습니다 (이미지 {plan.missing_alts}). "
                "이미지를 확인하고 alt 를 채운 뒤 다시 실행해 주세요."
            )
        return plan

    def _thumbnail_source(
        self,
        prop_value: dict[str, Any] | None,
        plan: PagePlan | None,
        slug: str,
        default_alt: str,
    ) -> tuple[str, bytes, str]:
        if plan and plan.thumbnail:
            path = plan_dir_for(self.plan_root, plan.page_id) / plan.thumbnail  # type: ignore[arg-type]
            return (
                target_filename(slug, None, path.name),
                path.read_bytes(),
                plan.thumbnail_alt or default_alt,
            )

        files = iter_files(prop_value)
        return (
            target_filename(slug, None, files[0].url, files[0].name),
            download(files[0].url),
            default_alt,
        )

    def _body_image_sources(
        self,
        prop_value: dict[str, Any] | None,
        plan: PagePlan | None,
        cand: Candidate,
        slug: str,
    ) -> list[tuple[str, bytes, Placement]]:
        assert cand.extracted is not None
        root = self.plan_root

        if plan and plan.images:
            out = []
            for img in sorted(plan.images, key=lambda i: (i.anchor, i.n)):
                path = plan_dir_for(root, plan.page_id) / img.original  # type: ignore[arg-type]
                out.append(
                    (
                        target_filename(slug, img.n, path.name),
                        path.read_bytes(),
                        Placement(index=img.anchor, alt=img.alt),
                    )
                )
            return out

        files = iter_files(prop_value)
        placements = plan_placements(
            cand.extracted.body,
            cand.extracted.image_hints,
            image_count=len(files),
            fallback_alt_prefix=cand.title,
        )
        return [
            (target_filename(slug, n, f.url, f.name), download(f.url), p)
            for n, (f, p) in enumerate(zip(files, placements, strict=True), start=1)
        ]

    def _mark_error(self, page_id: str) -> None:
        """실패한 행을 '발행 오류'로 표시합니다. 상태 옵션이 없으면 조용히 넘어갑니다."""
        # 임시저장 테스트는 노션을 일절 건드리지 않습니다.
        if self.dry_run or self.draft or not self.cfg.notion.status_error:
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
    drafted = [o for o in outcomes if o.drafted]
    prepared = [o for o in outcomes if o.prepared]
    failed = [o for o in outcomes if o.error]
    skipped = [o for o in outcomes if o.skipped]

    if prepared:
        headline = f"준비 {len(prepared)}건"
    elif drafted and not published:
        headline = f"임시저장 {len(drafted)}건"
    else:
        headline = f"발행 {len(published)}건"
    lines = [
        f"{headline} · 실패 {len(failed)}건 · 대기/제외 {len(skipped)}건",
        "",
    ]

    for o in prepared:
        lines.append(f"  📥 {o.title[:50]}\n     {o.plan_path}")
    for o in published:
        lines.append(f"  ✅ {o.title[:50]}\n     {o.link}")
    for o in drafted:
        lines.append(
            f"  📝 {o.title[:50]}  (임시저장, 비공개)\n"
            f"     편집: {o.edit_link}"
        )
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

    if prepared:
        lines += [
            "",
            "이미지를 내려받고 plan.json 을 만들었습니다. 아직 아무것도 발행하지 않았습니다.",
            "각 plan.json 의 images[].alt 를 채운 뒤 --plan 으로 다시 실행하세요.",
        ]

    if drafted:
        lines += [
            "",
            "임시저장한 글은 공개되지 않았고 노션도 그대로입니다.",
            "확인 후 --draft 없이 다시 돌리면 이 초안이 그대로 공개됩니다.",
            "버리려면 워드프레스에서 초안을 삭제하세요.",
        ]

    return "\n".join(lines)
