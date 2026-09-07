"""썸네일 생성 단계.

플래너에서 '제목은 있는데 썸네일이 없는' 행을 찾아 썸네일을 만들고, 그 행의
'썸네일' 칸에 첨부합니다. 워드프레스는 건드리지 않으므로 발행 대상이 아닌
고객사(원고 생성 전용)도 함께 처리합니다.

거르는 조건은 셋입니다:

    유형이 대상 유형에 든다        기본은 숏폼만
    제목이 있고 '템플릿'이 아니다   템플릿 이름이 남아 있으면 원고 생성 전입니다
    썸네일 칸이 비어 있다          사람이 올린 것을 덮어쓰지 않습니다

이미 붙어 있는 썸네일은 절대 건드리지 않습니다. 마음에 안 들면 사람이 지우고
다시 돌리면 새로 만들어집니다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import notion_api as napi
from .config import Config
from .designs import Design
from .designs import load as load_design
from .notion_api import NotionClient
from .runlog import Summary
from .thumbnail import badge_text, render, split_title

log = logging.getLogger(__name__)

#: 플래너 템플릿 행의 제목에 들어 있는 말. 이게 남아 있으면 원고 생성 전입니다.
TEMPLATE_MARK = "템플릿"

#: 당장은 숏폼만 만듭니다. 늘리려면 이 목록에 유형을 더하면 됩니다.
DEFAULT_TYPES = ("숏폼",)


@dataclass
class Outcome:
    """행 하나의 처리 결과."""

    title: str
    page_id: str = ""
    made: bool = False
    skipped: str = ""
    error: str = ""


@dataclass
class Report:
    client: str
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def made(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.made]

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.error]

    def summarize(self) -> Summary:
        """실행 로그 한 줄에 담을 요약. 발행 단계와 결과 모양이 달라 따로 만듭니다."""
        made, failed = self.made, self.failed

        if failed and made:
            result = "부분 성공"
        elif failed:
            result = "실패"
        elif made:
            result = "성공"
        else:
            result = "대상 없음"

        lines = [f"썸네일 {len(made)}건 · 실패 {len(failed)}건"]
        for o in made:
            lines.append(f"✅ {o.title[:60]}")
        for o in failed:
            lines.append(f"❌ {o.title[:60] or '(제목 없음)'} — {o.error[:200]}")

        return Summary(result=result, count=len(made), detail="\n".join(lines))


def has_file(prop: dict[str, Any] | None) -> bool:
    return bool((prop or {}).get("files"))


def eligible(
    props: dict[str, Any], cfg: Config, types: Sequence[str] = DEFAULT_TYPES
) -> tuple[bool, str]:
    """이 행에 썸네일을 만들어야 하는지. 아니면 (False, 사유)."""
    name = cfg.notion.prop

    kind = napi.read_select(props.get(name("type")))
    if types and kind not in types:
        return False, f"유형이 '{kind or '미지정'}'"

    title = napi.read_text(props.get(name("title"))).strip()
    if not title:
        return False, "제목이 비어 있음"
    if TEMPLATE_MARK in title:
        # 템플릿 이름이 그대로면 원고 생성이 아직 안 돌았거나 실패한 것입니다.
        return False, "제목이 아직 템플릿 이름"

    if has_file(props.get(name("thumbnail"))):
        return False, "썸네일이 이미 있음"

    return True, ""


def make_for_row(
    props: dict[str, Any], cfg: Config, design: Design
) -> tuple[bytes, str]:
    """행 하나의 썸네일 PNG 와 파일 이름."""
    name = cfg.notion.prop
    title = napi.read_text(props.get(name("title"))).strip()
    keywords = napi.read_text(props.get(name("keywords")))

    main, sub = split_title(title, design.client)
    png = render(
        main,
        sub,
        design.brand(),
        design.fonts(),
        badge=badge_text(keywords),
        palette=design.palette,
    )
    slug = napi.read_text(props.get(name("slug"))).strip()
    return png, f"{slug or 'thumbnail'}.png"


def run(
    cfg: Config,
    notion: NotionClient,
    *,
    types: Sequence[str] = DEFAULT_TYPES,
    dry_run: bool = False,
    limit: int = 0,
) -> Report:
    """한 고객사의 플래너를 훑어 썸네일을 만들고 붙입니다."""
    report = Report(client=cfg.client)

    design = load_design(cfg.client)
    if design is None:
        # 디자인이 없으면 만들지 않습니다. 아무 모양으로나 찍어내면 그 고객사
        # 썸네일이 제각각이 됩니다. 사람(또는 에이전트)이 한 번 정해야 합니다.
        report.outcomes.append(
            Outcome(title="", error=f"'{cfg.client}' 의 확정된 썸네일 디자인이 없습니다")
        )
        return report

    for row in notion.query_database(cfg.notion.database_id):
        props = row.get("properties") or {}
        title = napi.read_text(props.get(cfg.notion.prop("title"))).strip()

        ok, reason = eligible(props, cfg, types)
        if not ok:
            report.outcomes.append(Outcome(title=title, page_id=row.get("id", ""), skipped=reason))
            continue

        if limit and len(report.made) >= limit:
            report.outcomes.append(Outcome(title=title, skipped="이번 회차 처리 한도 초과"))
            continue

        outcome = Outcome(title=title, page_id=row.get("id", ""))
        try:
            png, filename = make_for_row(props, cfg, design)
            if dry_run:
                outcome.skipped = f"미리보기 ({len(png) // 1024}KB)"
            else:
                upload_id = notion.upload_file(png, filename, "image/png")
                notion.update_page(
                    outcome.page_id,
                    {cfg.notion.prop("thumbnail"): napi.write_files([(upload_id, filename)])},
                )
                outcome.made = True
                log.info("썸네일 첨부: %s", title[:50])
        except Exception as exc:  # 한 행이 실패해도 나머지 행은 계속 처리합니다.
            outcome.error = str(exc)[:300]
            log.warning("썸네일 실패 [%s]: %s", title[:40], exc)

        report.outcomes.append(outcome)

    return report
