"""리포트 대상 기간 계산.

리드젠랩 월간 리포트는 **직전 달의 작업 성과**를 **그 달 말일 기준 데이터**로
보고합니다. 루틴이 10월 1일에 돌면 대상은 2026년 9월이고, 데이터 기준일은
9월 30일이며, 콘텐츠 플래너 필터의 '작업년월'은 `2026.9` 입니다.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date


class PeriodError(ValueError):
    pass


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


@dataclass(frozen=True)
class Period:
    """리포트 한 건이 다루는 달."""

    year: int
    month: int

    #: 플래너 '작업년월' 선택지 이름. 0을 채우지 않습니다 (2026.9, 2026.10).
    @property
    def planner_option(self) -> str:
        return f"{self.year}.{self.month}"

    #: 리포트명 앞머리. 두 자리로 채웁니다 (26.09).
    @property
    def report_prefix(self) -> str:
        return f"{self.year % 100:02d}.{self.month:02d}"

    #: 데이터 기준일 = 그 달의 말일.
    @property
    def snapshot(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    #: 소하 CSV 파일명에 붙이는 연월 (prompts-2026-09.csv).
    @property
    def file_tag(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def shifted(self, delta: int) -> "Period":
        return Period(*_shift(self.year, self.month, delta))

    @property
    def previous(self) -> "Period":
        return self.shifted(-1)

    def report_name(self, client: str) -> str:
        return f"{self.report_prefix} {client} 리포트"

    def __str__(self) -> str:  # pragma: no cover - 로그용
        return self.file_tag


def target_period(run_on: date | None = None) -> Period:
    """루틴이 도는 날짜로부터 대상 달을 고릅니다 (= 직전 달)."""

    today = run_on or date.today()
    return Period(*_shift(today.year, today.month, -1))


def parse_period(text: str) -> Period:
    """`2026-09`, `2026.9`, `26.09` 를 모두 받습니다."""

    match = re.fullmatch(r"\s*(\d{2}|\d{4})\s*[-./]\s*(\d{1,2})\s*", text)
    if not match:
        raise PeriodError(f"연월로 읽을 수 없습니다: {text!r} (예: 2026-09)")
    year, month = int(match.group(1)), int(match.group(2))
    if year < 100:
        year += 2000
    if not 1 <= month <= 12:
        raise PeriodError(f"월이 1~12 가 아닙니다: {text!r}")
    return Period(year, month)


def resolve(text: str | None = None, run_on: date | None = None) -> Period:
    return parse_period(text) if text else target_period(run_on)
