"""브라우저 드라이버 — 실제 관리자 화면과 같은 모양의 가짜 사이트에 Chromium 으로 붙습니다.

가짜 사이트(`fake_board_site.py`)는 2026-09-09 제로클리닉 관리자에 로그인해 확인한
마크업을 그대로 옮긴 것입니다. 필드 이름(subject·visited·ishtml·contents),
그림으로 된 등록 버튼, 서머노트 초기화 방식이 실물과 같습니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("playwright")

from fake_board_site import PASSWORD, USER, FakeBoardSite
from notionwp.board import BoardClient, BoardError, BoardProfile
from notionwp.thumbnail import ThumbnailError, find_chromium

try:
    find_chromium()
except ThumbnailError:  # pragma: no cover
    pytest.skip("Chromium 이 없는 환경", allow_module_level=True)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def start(**kwargs) -> FakeBoardSite:
    site = FakeBoardSite(**kwargs)
    site.base = site.start()
    return site


@pytest.fixture
def site():
    fake = start()
    yield fake
    fake.stop()


def profile_for(site) -> BoardProfile:
    """실제 제로클리닉 프로파일과 같은 설정 (주소만 가짜 서버로)."""
    return BoardProfile(
        host="127.0.0.1",
        admin_url=f"{site.base}/admin/board/boardseo_list.php",
        login_url=f"{site.base}/admin/Login.php",
        public_url=f"{site.base}/htm/boardseo_read.php?id={{id}}",
        tab="",
        submit_selector="a[href*='checkForm']",
        html_mode_value="Y",
    )


def compose_for(seen: dict):
    def compose(urls):
        seen["urls"] = urls
        return (
            "<title>새 글</title>\n"
            '<h1 style="font-size: 20px;">새 글 제목</h1>\n'
            "<p>본문</p>\n"
            f'<p><br></p><div><img src="{urls[0]}" alt="첫 사진"></div>\n'
            f'<div><img src="{urls[1]}" alt="둘째"></div>'
        )

    return compose


def test_login_list_publish_round_trip(site, tmp_path):
    seen: dict = {}

    with BoardClient(profile_for(site), USER, PASSWORD, artifacts=tmp_path) as client:
        client.login()
        assert site.login_attempts == [(USER, PASSWORD)]

        # 기존 글은 찾고(화면 번호가 아니라 진짜 id 를 집어야 합니다), 없는 글은 None.
        found = client.find_post("기존 글 하나")
        assert found is not None and found.id == "161"
        assert found.link.endswith("id=161")
        assert client.find_post("없는 제목") is None

        post = client.publish(
            title="새 글 제목",
            hit=777,
            images=[("a.png", PNG), ("b.png", PNG)],
            compose=compose_for(seen),
        )

    assert post.id == "162"
    assert post.link.endswith("id=162")

    # 서버가 준 주소가 본문에 들어갔고, 업로드는 두 번 일어났습니다.
    assert site.uploads == 2
    assert seen["urls"] == [
        f"{site.base}/files/editor/20260901.jpg",
        f"{site.base}/files/editor/20260902.jpg",
    ]

    saved = site.posts[0]
    assert saved["title"] == "새 글 제목"
    assert saved["visited"] == 777
    assert saved["ishtml"] == "Y", "HTML 모드가 선택되어야 합니다"
    assert saved["isnoti"] == "N", "공지가 아니라 일반이어야 합니다"
    assert saved["udate"], "작성일 기본값을 지우면 안 됩니다"
    # 본문은 서머노트가 채운 hidden contents 로 넘어갑니다.
    assert "<title>새 글</title>" in saved["contents"]
    assert 'alt="첫 사진"' in saved["contents"]
    # 업로드하면서 잠깐 들어갔던 <img> 는 최종 본문에 남지 않습니다 (우리 HTML 의 두 장만).
    assert saved["contents"].count("<img") == 2

    assert list(tmp_path.glob("*-before-submit.png"))


def test_publish_works_without_summernote_via_codeview(tmp_path):
    """에디터 스크립트가 없으면 코드 보기(</>) 칸으로 본문을 넣습니다."""
    fake = start(jquery=False)
    try:
        with BoardClient(profile_for(fake), USER, PASSWORD) as client:
            client.login()
            client.publish(
                title="폴백 글", hit=600, images=[("a.png", PNG), ("b.png", PNG)],
                compose=compose_for({}),
            )
        assert "<title>새 글</title>" in fake.posts[0]["contents"]
    finally:
        fake.stop()


def test_wrong_password_fails_with_a_screenshot(site, tmp_path):
    with BoardClient(profile_for(site), USER, "wrong", artifacts=tmp_path) as client:
        with pytest.raises(BoardError, match="로그인에 실패") as info:
            client.login()
    assert "화면:" in str(info.value)
    # 서버가 띄운 알림을 그대로 옮겨 줘야 사람이 원인을 압니다.
    assert "패스워드가 틀립니다" in str(info.value)
    assert list(tmp_path.glob("*-login-failed.png"))


def test_inspect_dumps_the_form(site, tmp_path):
    with BoardClient(profile_for(site), USER, PASSWORD) as client:
        report_path = client.inspect(tmp_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    names = {f["name"] for f in report["form_fields"]}
    assert {"subject", "visited", "contents", "ishtml", "udate"} <= names
    rows = {f["row"] for f in report["form_fields"] if f["name"] == "subject"}
    assert rows == {"제목"}
    assert report["editor"]["summernote"] is True
    assert "codeview" in report["editor"]["toolbar_buttons"]
    assert any(step["step"] == "write" for step in report["steps"])


def test_inspect_still_writes_a_report_when_login_fails(site, tmp_path):
    with BoardClient(profile_for(site), USER, "wrong") as client:
        with pytest.raises(BoardError):
            client.inspect(tmp_path)

    report = json.loads((tmp_path / "inspect.json").read_text(encoding="utf-8"))
    assert "로그인에 실패" in report["login_error"]
    assert report["steps"] == []
