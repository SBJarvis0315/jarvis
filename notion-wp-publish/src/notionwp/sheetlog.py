"""노션 콘텐츠 플래너 → 마스터 시트 '발행 로그' 자동 기입.

플래너에서 **발행이 끝난 행**(제목·유형·발행 예정일·URL 이 모두 채워진 행)을 골라
고객사 마스터 시트의 발행 로그 탭에 한 줄씩 옮겨 적습니다.

설계에서 지킨 두 가지:

* **덧쓰지 않습니다.** 이미 무언가 적혀 있는 줄은 건드리지 않고, 빈 줄만 채웁니다.
  마스터 시트는 고객사와 함께 보는 문서라 사람이 손으로 적은 값을 자동화가 지우면 안 됩니다.
* **몇 번을 돌려도 같습니다.** 게재본 주소로 이미 적힌 것을 걸러내므로, 루틴이 하루에
  두 번 돌든 실패 후 다시 돌든 같은 글이 두 줄로 늘어나지 않습니다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import notion_api as napi
from .gsheets import SheetsClient, a1_cell

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "sheet-log.json"

#: 시트 → 노션 대응. 왼쪽이 시트 헤더, 오른쪽이 플래너 속성입니다.
DEFAULT_COLUMNS = {"date": "날짜", "type": "콘텐츠 유형", "title": "제목", "url": "게재본"}
DEFAULT_PROPERTIES = {"date": "발행 예정일", "type": "유형", "title": "제목", "url": "URL"}

#: 헤더 줄을 찾을 때 훑어볼 윗줄 수. 안내 문구가 몇 줄 붙어 있어도 넉넉합니다.
HEADER_SCAN_ROWS = 20

_UUID = re.compile(r"[0-9a-fA-F]{32}")


class SheetLogError(RuntimeError):
    pass


# ------------------------------------------------------------------------ 설정


@dataclass
class Target:
    """고객사 한 곳의 플래너와 마스터 시트를 잇는 설정."""

    client: str
    planner_db: str
    spreadsheet: str
    sheet: str = ""
    #: 플래너 속성 이름. 고객사마다 다를 수 있어 설정으로 둡니다.
    properties: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PROPERTIES))
    #: 시트 헤더 이름.
    columns: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_COLUMNS))
    #: 비우면 상태를 보지 않고 URL 유무로만 판단합니다. 값을 넣으면 그 상태만 옮깁니다.
    status_done: list[str] = field(default_factory=list)
    status_property: str = "진행 상황"

    def prop(self, key: str) -> str:
        name = self.properties.get(key) or DEFAULT_PROPERTIES.get(key, "")
        if not name:
            raise SheetLogError(f"'{self.client}' 설정에 properties.{key} 가 없습니다.")
        return name

    def column(self, key: str) -> str:
        name = self.columns.get(key) or DEFAULT_COLUMNS.get(key, "")
        if not name:
            raise SheetLogError(f"'{self.client}' 설정에 columns.{key} 가 없습니다.")
        return name


def normalize_id(value: str) -> str:
    """노션 주소를 통째로 붙여넣어도 32자리 ID만 뽑아냅니다."""
    raw = (value or "").strip().replace("-", "")
    match = _UUID.search(raw)
    return match.group(0) if match else ""


def load_targets(path: str | Path | None = None, *, only: str = "") -> list[Target]:
    config_path = Path(path) if path else CONFIG_PATH
    if not config_path.is_file():
        raise SheetLogError(
            f"설정 파일이 없습니다: {config_path}\n"
            f"  config/sheet-log.json 에 고객사별 플래너 DB와 마스터 시트를 적어 주세요."
        )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SheetLogError(f"설정 파일을 읽지 못했습니다 ({config_path}): {exc}") from exc

    targets: list[Target] = []
    for item in raw.get("targets", []):
        try:
            target = Target(**item)
        except TypeError as exc:
            raise SheetLogError(f"설정 항목이 올바르지 않습니다 ({config_path}): {exc}") from exc

        target.planner_db = normalize_id(target.planner_db)
        if not target.planner_db:
            raise SheetLogError(f"'{target.client}' 의 planner_db 가 노션 DB ID 형식이 아닙니다.")
        if not target.spreadsheet:
            raise SheetLogError(f"'{target.client}' 의 spreadsheet 가 비어 있습니다.")
        if only and only not in target.client:
            continue
        targets.append(target)

    return targets


# ------------------------------------------------------------------ 플래너 읽기


@dataclass
class Entry:
    """시트에 한 줄로 들어갈 값."""

    date: str
    type: str
    title: str
    url: str

    def cell(self, key: str) -> str:
        return getattr(self, key)


@dataclass
class Skipped:
    title: str
    reason: str


def normalize_url(url: str) -> str:
    """같은 글인지 비교하기 위한 형태. 앞뒤 공백과 끝의 빗금 차이는 무시합니다."""
    return (url or "").strip().rstrip("/")


def collect(rows: list[dict[str, Any]], target: Target) -> tuple[list[Entry], list[Skipped]]:
    """플래너 행 → 시트에 옮길 값. 네 칸이 모두 찬 행만 통과시킵니다."""
    entries: list[Entry] = []
    skipped: list[Skipped] = []

    for row in rows:
        props = row.get("properties") or {}
        title = napi.read_text(props.get(target.prop("title"))).strip()
        url = napi.read_url(props.get(target.prop("url"))).strip()
        ctype = napi.read_select(props.get(target.prop("type"))).strip()
        date = napi.read_date(props.get(target.prop("date")))[:10]

        if not url:
            # 아직 발행 전인 행입니다. 매달 수십 개라 사유를 남기면 로그가 묻힙니다.
            continue

        if target.status_done:
            status = napi.read_select(props.get(target.status_property)).strip()
            if status not in target.status_done:
                skipped.append(Skipped(title or "(제목 없음)", f"진행 상황이 '{status or '미지정'}'"))
                continue

        missing = [
            label
            for label, value in (
                (target.column("title"), title),
                (target.column("type"), ctype),
                (target.column("date"), date),
            )
            if not value
        ]
        if missing:
            # URL까지 넣어놓고 다른 칸이 빈 것은 사람이 채워야 할 일이라 눈에 띄게 남깁니다.
            skipped.append(Skipped(title or url, f"{' · '.join(missing)} 이(가) 비어 있음"))
            continue

        entries.append(Entry(date=date, type=ctype, title=title, url=url))

    # 오래된 것부터 쌓이도록 정렬합니다. 같은 날짜는 제목 순으로 고정해 두면
    # 실행할 때마다 순서가 흔들리지 않습니다.
    entries.sort(key=lambda e: (e.date, e.title))
    return entries, skipped


# -------------------------------------------------------------------- 시트 읽기


@dataclass
class Header:
    """발행 로그 표의 머리. 어느 줄이 헤더이고 각 항목이 몇 번째 열인지."""

    row: int
    columns: dict[str, int]


def find_header(values: list[list[str]], target: Target) -> Header:
    wanted = {key: target.column(key) for key in DEFAULT_COLUMNS}

    for index, row in enumerate(values[:HEADER_SCAN_ROWS]):
        cells = {str(c).strip(): pos for pos, c in enumerate(row)}
        found = {key: cells[label] for key, label in wanted.items() if label in cells}
        if len(found) == len(wanted):
            return Header(row=index, columns=found)

    raise SheetLogError(
        f"'{target.sheet or '첫 번째 탭'}' 에서 헤더 줄을 찾지 못했습니다. "
        f"{' · '.join(wanted.values())} 이(가) 한 줄에 모두 있어야 합니다."
    )


def cell_at(values: list[list[str]], row: int, col: int) -> str:
    if row >= len(values) or col >= len(values[row]):
        return ""
    return str(values[row][col]).strip()


def logged_urls(values: list[list[str]], header: Header) -> set[str]:
    url_col = header.columns["url"]
    return {
        normalize_url(cell_at(values, row, url_col))
        for row in range(header.row + 1, len(values))
        if cell_at(values, row, url_col)
    }


@dataclass
class Plan:
    """이번 실행에서 시트에 더할 것. 칸 목록과, 그 칸을 만든 원고들."""

    added: list[Entry] = field(default_factory=list)
    cells: list[tuple[str, str]] = field(default_factory=list)


def plan_writes(values: list[list[str]], header: Header, entries: list[Entry], target: Target) -> Plan:
    """빈 줄부터 채우고, 모자라면 표 아래에 이어 붙입니다. 이미 적힌 줄은 건드리지 않습니다."""
    already = logged_urls(values, header)
    title_col, url_col = header.columns["title"], header.columns["url"]

    # 유형만 미리 적어둔 예정 줄이 표에 깔려 있습니다. 제목과 게재본이 둘 다 비어야
    # 아직 아무도 쓰지 않은 줄입니다.
    blanks = [
        row
        for row in range(header.row + 1, len(values))
        if not cell_at(values, row, title_col) and not cell_at(values, row, url_col)
    ]
    next_row = len(values)

    plan = Plan()
    for entry in entries:
        if normalize_url(entry.url) in already:
            continue
        already.add(normalize_url(entry.url))

        if blanks:
            row = blanks.pop(0)
        else:
            row, next_row = next_row, next_row + 1

        plan.added.append(entry)
        for key, col in header.columns.items():
            plan.cells.append((a1_cell(target.sheet, row, col), entry.cell(key)))

    return plan


# ---------------------------------------------------------------------- 실행


@dataclass
class Result:
    """실행 로그에 그대로 넘기기 위해 발행 결과와 같은 모양을 씁니다."""

    title: str
    date: str = ""
    published: bool = False
    skipped: bool = False
    link: str = ""
    error: str = ""
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Syncer:
    def __init__(self, target: Target, notion: Any, sheets: SheetsClient, *, dry_run: bool = False):
        self.target = target
        self.notion = notion
        self.sheets = sheets
        self.dry_run = dry_run

    def run(self) -> list[Result]:
        target = self.target
        rows = self.notion.query_database(target.planner_db)
        entries, skipped = collect(rows, target)
        log.info("[%s] 플래너에서 발행 완료 %d건을 읽었습니다", target.client, len(entries))

        values = self.sheets.read(target.spreadsheet, target.sheet)
        header = find_header(values, target)
        plan = plan_writes(values, header, entries, target)

        if plan.cells and not self.dry_run:
            written = self.sheets.write_cells(target.spreadsheet, plan.cells)
            log.info("[%s] 마스터 시트에 %d개 칸을 채웠습니다", target.client, written)
        elif plan.cells:
            log.info("[%s] (--dry-run) %d건을 기입할 예정입니다", target.client, len(plan.added))

        results = [
            Result(title=e.title, date=e.date, published=True, link=e.url) for e in plan.added
        ]
        results += [Result(title=s.title, skipped=True, reasons=[s.reason]) for s in skipped]
        return results


def summarize(target: Target, results: list[Result], *, dry_run: bool = False) -> str:
    added = [r for r in results if r.published]
    held = [r for r in results if r.skipped]

    head = "기입 예정" if dry_run else "기입"
    lines = [f"[{target.client}] {head} {len(added)}건"]
    for r in added:
        lines.append(f"  + {r.date}  {r.title}")
    for r in held:
        lines.append(f"  ⏸ {r.title} — {'; '.join(r.reasons)}")
    if not added and not held:
        lines.append("  새로 적을 것이 없습니다.")
    return "\n".join(lines)
