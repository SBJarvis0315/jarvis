"""플래너 → 마스터 시트 '발행 로그' 기입.

확인하려는 것:
  · 발행이 끝난 행만 골라내는가 (URL이 채워진 행)
  · 고객사가 이미 적어둔 줄을 덮어쓰지 않는가
  · 두 번 돌려도 같은 글이 두 줄이 되지 않는가
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notionwp.gsheets import a1_cell, a1_column, quote_sheet
from notionwp.sheetlog import (
    Entry,
    SheetLogError,
    Syncer,
    Target,
    collect,
    find_header,
    load_targets,
    logged_urls,
    normalize_url,
    plan_writes,
    summarize,
)

SHEET = "7) 발행 로그"


def target(**kwargs) -> Target:
    base = dict(
        client="제로클리닉",
        planner_db="37b68fa206ff80c5a520e7500fac7d0e",
        spreadsheet="sheet-id",
        sheet=SHEET,
    )
    base.update(kwargs)
    return Target(**base)


def page(title="제목", *, ctype="숏폼", date="2026-07-29", url="https://ex.test/1", status="발행완료"):
    props = {
        "제목": {"type": "title", "title": [{"type": "text", "plain_text": title}]},
        "유형": {"type": "select", "select": {"name": ctype} if ctype else None},
        "발행 예정일": {"type": "date", "date": {"start": date} if date else None},
        "URL": {"type": "url", "url": url or None},
        "진행 상황": {"type": "status", "status": {"name": status} if status else None},
    }
    return {"id": "p", "properties": props}


#: 실제 마스터 시트 모양. 2행에 안내 문구, 3행이 헤더, 그 아래는 유형만 미리 적힌 예정 줄.
def blank_sheet(rows: int = 4) -> list[list[str]]:
    values = [
        [],
        ["", "", "", "- 월 발행 건수: 롱폼 6건 / 숏폼 20건"],
        ["", "날짜", "콘텐츠 유형", "제목", "게재본"],
    ]
    values += [["", "", "숏폼"] for _ in range(rows)]
    return values


# ------------------------------------------------------------------ 주소 계산


def test_a1_addresses():
    assert a1_column(0) == "A"
    assert a1_column(4) == "E"
    assert a1_column(26) == "AA"
    assert quote_sheet(SHEET) == "'7) 발행 로그'!"
    assert a1_cell(SHEET, 3, 1) == "'7) 발행 로그'!B4"
    assert a1_cell("", 0, 0) == "A1"


# ------------------------------------------------------------------ 플래너 읽기


def test_only_rows_with_a_published_link():
    entries, skipped = collect([page(), page("아직 발행 전", url="")], target())
    assert [e.title for e in entries] == ["제목"]
    assert skipped == []  # 발행 전 행은 매달 수십 개라 사유를 남기지 않습니다


def test_link_without_the_rest_is_reported():
    entries, skipped = collect([page("유형 빠짐", ctype="")], target())
    assert entries == []
    assert "콘텐츠 유형" in skipped[0].reason


def test_entries_are_sorted_oldest_first():
    rows = [
        page("나중", date="2026-07-29", url="https://ex.test/2"),
        page("먼저", date="2026-06-10", url="https://ex.test/1"),
    ]
    entries, _ = collect(rows, target())
    assert [e.title for e in entries] == ["먼저", "나중"]


def test_status_filter_is_optional():
    rows = [page("작성 중", status="피드백 진행중")]
    assert len(collect(rows, target())[0]) == 1  # 기본값은 상태를 보지 않습니다

    entries, skipped = collect(rows, target(status_done=["발행완료"]))
    assert entries == []
    assert "피드백 진행중" in skipped[0].reason


# ---------------------------------------------------------------------- 헤더


def test_header_is_found_below_the_notice_row():
    header = find_header(blank_sheet(), target())
    assert header.row == 2
    assert header.columns == {"date": 1, "type": 2, "title": 3, "url": 4}


def test_missing_header_says_what_it_looked_for():
    with pytest.raises(SheetLogError, match="게재본"):
        find_header([["아무것도", "없음"]], target())


# ------------------------------------------------------------------ 기입 계획


def entry(title="제목", url="https://ex.test/1", date="2026-07-29", ctype="숏폼") -> Entry:
    return Entry(date=date, type=ctype, title=title, url=url)


def test_prefilled_rows_are_used_before_the_table_grows():
    values = blank_sheet(rows=2)
    plan = plan_writes(values, find_header(values, target()), [entry()], target())

    assert [e.title for e in plan.added] == ["제목"]
    assert dict(plan.cells) == {
        "'7) 발행 로그'!B4": "2026-07-29",
        "'7) 발행 로그'!C4": "숏폼",
        "'7) 발행 로그'!D4": "제목",
        "'7) 발행 로그'!E4": "https://ex.test/1",
    }


def test_table_grows_when_the_prefilled_rows_run_out():
    values = blank_sheet(rows=1)
    entries = [entry("첫째", "https://ex.test/1"), entry("둘째", "https://ex.test/2")]
    plan = plan_writes(values, find_header(values, target()), entries, target())

    rows = sorted({rng.rsplit("!", 1)[1][1:] for rng, _ in plan.cells})
    assert rows == ["4", "5"]


def test_rows_people_already_wrote_are_left_alone():
    values = blank_sheet(rows=2)
    values[3] = ["", "2026-01-01", "롱폼", "손으로 적은 글", "https://ex.test/hand"]

    plan = plan_writes(values, find_header(values, target()), [entry()], target())
    written_rows = {rng.rsplit("!", 1)[1][1:] for rng, _ in plan.cells}
    assert written_rows == {"5"}  # 4행은 그대로 둡니다


def test_already_logged_links_are_not_repeated():
    values = blank_sheet(rows=2)
    values[3] = ["", "2026-07-29", "숏폼", "제목", "https://ex.test/1/"]

    plan = plan_writes(values, find_header(values, target()), [entry()], target())
    assert plan.added == []
    assert plan.cells == []


def test_link_comparison_ignores_a_trailing_slash():
    assert normalize_url("https://ex.test/1/ ") == normalize_url("https://ex.test/1")


def test_logged_urls_reads_only_below_the_header():
    values = blank_sheet(rows=1)
    values[3] = ["", "", "숏폼", "제목", "https://ex.test/1"]
    assert logged_urls(values, find_header(values, target())) == {"https://ex.test/1"}


# ------------------------------------------------------------------ 전체 실행


class FakeNotion:
    def __init__(self, rows):
        self.rows = rows
        self.created: list[tuple[str, dict]] = []

    def query_database(self, database_id):
        return self.rows

    def create_page(self, database_id, properties):
        self.created.append((database_id, properties))
        return {}


class FakeSheets:
    def __init__(self, values):
        self.values = values
        self.written: list[tuple[str, str]] = []

    def read(self, spreadsheet_id, sheet, **kwargs):
        return self.values

    def write_cells(self, spreadsheet_id, cells):
        self.written.extend(cells)
        return len(cells)


def test_run_writes_new_rows_and_reports_them():
    sheets = FakeSheets(blank_sheet(rows=2))
    results = Syncer(target(), FakeNotion([page()]), sheets).run()

    assert len(sheets.written) == 4
    assert [r.title for r in results if r.published] == ["제목"]


def test_dry_run_touches_nothing():
    sheets = FakeSheets(blank_sheet(rows=2))
    results = Syncer(target(), FakeNotion([page()]), sheets, dry_run=True).run()

    assert sheets.written == []
    assert [r.title for r in results if r.published] == ["제목"]


def test_second_run_adds_nothing():
    values = blank_sheet(rows=2)
    sheets = FakeSheets(values)
    Syncer(target(), FakeNotion([page()]), sheets).run()

    # 첫 실행 결과를 시트에 반영한 뒤 다시 돌립니다.
    values[3] = ["", "2026-07-29", "숏폼", "제목", "https://ex.test/1"]
    sheets.written.clear()
    results = Syncer(target(), FakeNotion([page()]), sheets).run()

    assert sheets.written == []
    assert [r for r in results if r.published] == []


def test_summary_lists_what_went_in():
    rows = [page(), page("유형 빠짐", ctype="", url="https://ex.test/2")]
    results = Syncer(target(), FakeNotion(rows), FakeSheets(blank_sheet())).run()
    text = summarize(target(), results)

    assert "기입 1건" in text
    assert "유형 빠짐" in text


# ---------------------------------------------------------------------- 설정


def test_config_file_is_read(tmp_path):
    path = tmp_path / "sheet-log.json"
    path.write_text(
        '{"targets": [{"client": "가", "planner_db": '
        '"https://notion.so/37b68fa206ff80c5a520e7500fac7d0e?v=1", "spreadsheet": "s"}]}',
        encoding="utf-8",
    )
    targets = load_targets(path)

    assert targets[0].planner_db == "37b68fa206ff80c5a520e7500fac7d0e"
    assert targets[0].column("url") == "게재본"  # 생략하면 기본 이름을 씁니다


def test_bad_planner_id_is_rejected(tmp_path):
    path = tmp_path / "sheet-log.json"
    path.write_text(
        '{"targets": [{"client": "가", "planner_db": "??", "spreadsheet": "s"}]}', encoding="utf-8"
    )
    with pytest.raises(SheetLogError, match="planner_db"):
        load_targets(path)


def test_shipped_config_matches_the_master_sheet():
    targets = load_targets()
    assert targets, "config/sheet-log.json 에 대상이 하나도 없습니다"
    assert all(t.sheet for t in targets)


# ------------------------------------------------------------------ 구글 인증


@functools.lru_cache(maxsize=1)
def _test_key() -> str:
    """테스트용 RSA 키.

    서명 자체는 표준 라이브러리로 하지만, 키를 만드는 것까지 손으로 할 일은 아니라
    테스트에서만 cryptography 를 씁니다. 없으면 이 절의 테스트만 건너뜁니다.
    """
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def service_account_info() -> dict:
    return {
        "type": "service_account",
        "client_email": "자동화@example.iam.gserviceaccount.com",
        "private_key": _test_key(),
        "token_uri": "https://oauth2.test/token",
    }


def test_signature_verifies_against_the_public_key():
    """서명이 그 키로 검증되는지를 라이브러리 없이 직접 확인합니다."""
    from notionwp.gsheets import _SHA256_PREFIX, _der_ints, _der_read, private_numbers, rs256_sign

    pem = _test_key()
    modulus, _ = private_numbers(pem)
    signature = rs256_sign(pem, b"hello")

    # 같은 DER 에서 공개 지수(3번째 정수)를 꺼내 서명을 되풀어 봅니다.
    body = "".join(x for x in pem.splitlines() if x and not x.startswith("-----"))
    _, outer, _ = _der_read(base64.b64decode(body), 0)
    _, _, pos = _der_read(outer, 0)
    _, _, pos = _der_read(outer, pos)
    _, wrapped, _ = _der_read(outer, pos)
    _, inner, _ = _der_read(wrapped, 0)
    _, _, public_exponent = _der_ints(inner, 3)

    size = (modulus.bit_length() + 7) // 8
    digest_info = _SHA256_PREFIX + hashlib.sha256(b"hello").digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info

    recovered = pow(int.from_bytes(signature, "big"), public_exponent, modulus)
    assert recovered.to_bytes(size, "big") == expected
    assert len(signature) == size


def test_signature_matches_the_reference_library():
    hashes = pytest.importorskip("cryptography.hazmat.primitives.hashes")
    padding = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.padding")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")

    from notionwp.gsheets import rs256_sign

    pem = _test_key()
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    assert rs256_sign(pem, b"payload") == key.sign(b"payload", padding.PKCS1v15(), hashes.SHA256())


def test_broken_key_says_so():
    from notionwp.gsheets import SheetsError, rs256_sign

    with pytest.raises(SheetsError, match="PEM 형식이 아닙니다"):
        rs256_sign("", b"x")
    with pytest.raises(SheetsError, match="읽지 못했습니다"):
        rs256_sign("-----BEGIN PRIVATE KEY-----\nZm9v\n-----END PRIVATE KEY-----", b"x")


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.ok = status < 400
        self.text = str(payload)
        self.headers: dict[str, str] = {}

    def json(self):
        return self.payload


class FakeSession:
    """토큰 발급과 시트 호출을 가로채는 세션."""

    def __init__(self, token_payload=None):
        self.token_payload = token_payload or {"access_token": "tok", "expires_in": 3600}
        self.posts: list[tuple[str, dict]] = []
        self.calls: list[tuple[str, str, dict]] = []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, data or {}))
        return FakeResponse(self.token_payload)

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.calls.append((method, url, dict(headers or {})))
        return FakeResponse({"values": [["날짜", "콘텐츠 유형", "제목", "게재본"]]})


def test_access_token_is_a_signed_jwt_exchange():
    from notionwp.gsheets import SheetsClient

    info = service_account_info()
    session = FakeSession()
    SheetsClient(info, session=session).read("sheet-id", SHEET)

    url, form = session.posts[0]
    assert url == "https://oauth2.test/token"
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"

    header, claims, signature = form["assertion"].split(".")
    payload = json.loads(base64.urlsafe_b64decode(claims + "=="))
    assert payload["iss"] == info["client_email"]
    assert payload["scope"] == "https://www.googleapis.com/auth/spreadsheets"
    assert payload["aud"] == "https://oauth2.test/token"
    assert "=" not in header + claims + signature  # base64url 은 채움 문자를 뺍니다
    assert session.calls[0][2]["Authorization"] == "Bearer tok"


def test_token_is_reused_across_calls():
    from notionwp.gsheets import SheetsClient

    session = FakeSession()
    client = SheetsClient(service_account_info(), session=session)
    client.read("sheet-id", SHEET)
    client.read("sheet-id", SHEET)

    assert len(session.posts) == 1  # 두 번째 호출은 받아둔 토큰을 씁니다


def test_credentials_env_accepts_json_or_a_path(tmp_path):
    from notionwp.gsheets import SheetsError, load_credentials_info

    info = service_account_info()
    assert load_credentials_info({"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(info)})["client_email"]

    path = tmp_path / "key.json"
    path.write_text(json.dumps(info), encoding="utf-8")
    assert load_credentials_info({"GOOGLE_SERVICE_ACCOUNT_JSON": str(path)})["client_email"]

    with pytest.raises(SheetsError, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
        load_credentials_info({})
    with pytest.raises(SheetsError, match="찾을 수 없습니다"):
        load_credentials_info({"GOOGLE_SERVICE_ACCOUNT_JSON": str(tmp_path / "없음.json")})
    with pytest.raises(SheetsError, match="서비스 계정 키가 아닙니다"):
        load_credentials_info({"GOOGLE_SERVICE_ACCOUNT_JSON": '{"a": 1}'})


def test_sharing_mistake_is_explained_with_the_account_address():
    from notionwp.gsheets import SheetsClient, SheetsError

    class Forbidden(FakeSession):
        def request(self, method, url, headers=None, timeout=None, **kwargs):
            return FakeResponse({"error": "denied"}, status=403)

    client = SheetsClient(service_account_info(), session=Forbidden())
    with pytest.raises(SheetsError, match=r"iam\.gserviceaccount\.com"):
        client.read("sheet-id", SHEET)
