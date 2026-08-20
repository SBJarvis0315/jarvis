"""실행 결과를 노션 '자동화 실행 로그' DB에 한 줄 남깁니다.

1단계(원고 생성) 루틴은 예전부터 이 DB에 로그를 남기고 있었고, 2단계(워드프레스 발행)는
남기지 않아 운영 로그가 반쪽이었습니다. 이 모듈이 그 빈자리를 채웁니다.

로그 쓰기는 부가 기능입니다. 여기서 무슨 일이 생겨도 발행 결과를 되돌리지 않고,
경고만 남기고 넘어갑니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from . import notion_api as napi
from .config import RunLogConfig

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

#: 노션 rich_text 한 조각의 상한. 상세는 이 안에서 잘라 담습니다.
DETAIL_LIMIT = 2000


class _Creator(Protocol):
    def create_page(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class Summary:
    """로그 한 줄에 담길 값. 결과 판정과 문장 만들기를 여기서 끝냅니다."""

    result: str
    count: int
    detail: str


def summarize_for_log(outcomes: list[Any]) -> Summary:
    published = [o for o in outcomes if o.published]
    failed = [o for o in outcomes if o.error]
    skipped = [o for o in outcomes if o.skipped]

    if failed and published:
        result = "부분 성공"
    elif failed:
        result = "실패"
    elif published:
        result = "성공"
    else:
        result = "대상 없음"

    lines = [
        f"발행 {len(published)}건 · 실패 {len(failed)}건 · 대기/제외 {len(skipped)}건"
    ]

    for o in published:
        lines.append(f"✅ {o.title[:60]} — {o.link}")
    for o in failed:
        lines.append(f"❌ {o.title[:60]} — {o.error[:200]}")

    for o in outcomes:
        for warning in getattr(o, "warnings", []):
            lines.append(f"⚠️ {o.title[:60]} — {warning[:200]}")

    # 아직 작성 중인 행까지 나열하면 정작 봐야 할 것이 묻힙니다.
    # 발행 직전까지 갔다가 걸린 것만 남깁니다.
    for o in skipped:
        if not o.reasons:
            continue
        if any("진행 상황이" in r or "유형이" in r for r in o.reasons):
            continue
        lines.append(f"⏸ {o.title[:60]} — {'; '.join(o.reasons)[:200]}")

    return Summary(result=result, count=len(published), detail="\n".join(lines))


class RunLogger:
    """설정에 로그 DB가 있을 때만 동작합니다. 없으면 조용히 아무것도 하지 않습니다."""

    def __init__(self, cfg: RunLogConfig, client: str, notion: _Creator):
        self.cfg = cfg
        self.client = client
        self.notion = notion

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.database_id)

    def write(self, outcomes: list[Any], *, note: str = "") -> None:
        if not self.enabled:
            return

        summary = summarize_for_log(outcomes)
        detail = f"{note}\n{summary.detail}" if note else summary.detail
        now = datetime.now(KST).replace(microsecond=0)

        prop = self.cfg.prop
        properties: dict[str, Any] = {
            prop("title"): {
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": (
                                f"{now:%Y-%m-%d %H:%M} {self.client} · {self.cfg.stage}"
                            )
                        },
                    }
                ]
            },
            prop("date"): {"date": {"start": now.isoformat()}},
            prop("client"): napi.write_text(self.client),
            prop("count"): {"number": summary.count},
            prop("result"): {"select": {"name": summary.result}},
            prop("detail"): napi.write_text(detail[:DETAIL_LIMIT]),
        }

        stage_prop = self.cfg.properties.get("stage")
        if stage_prop:
            properties[stage_prop] = {"select": {"name": self.cfg.stage}}

        try:
            self.notion.create_page(self.cfg.database_id, properties)
            log.info("실행 로그를 남겼습니다 (%s · %s건)", summary.result, summary.count)
        except Exception as exc:  # 로그 실패가 발행을 되돌리게 두지 않습니다.
            log.warning("실행 로그를 남기지 못했습니다: %s", exc)
