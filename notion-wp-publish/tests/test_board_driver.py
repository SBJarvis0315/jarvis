"""브라우저 드라이버 — 가짜 관리자 사이트에 실제 Chromium 으로 붙여 봅니다.

Playwright 나 Chromium 이 없는 환경에서는 건너뜁니다. 실제 사이트와 100% 같을 수는
없지만, 드라이버가 의지하는 DOM 조각과 흐름(로그인 → 목록 → 글쓰기 → 이미지 →
코드 보기 → 등록 → 목록 대조)이 돌아가는지는 여기서 확인합니다.
"""

from __future__ import annotations

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


@pytest.fixture
def site():
    fake = FakeBoardSite()
    base = fake.start()
    fake.base = base
    yield fake
    fake.stop()


def profile_for(site) -> BoardProfile:
    return BoardProfile(
        host="127.0.0.1",
        admin_url=f"{site.base}/admin/board/main.php",
        public_url=f"{site.base}/htm/boardseo_read.php?id={{id}}",
        tab="블로그",
    )


def test_login_list_publish_round_trip(site, tmp_path):
    profile = profile_for(site)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    with BoardClient(profile, USER, PASSWORD, artifacts=tmp_path) as client:
        client.login()
        assert site.login_attempts == [(USER, PASSWORD)]

        # 기존 글은 찾고, 없는 글은 None.
        found = client.find_post("기존 글 하나")
        assert found is not None and found.id == "161"
        assert found.link.endswith("id=161")
        assert client.find_post("없는 제목") is None

        seen: dict = {}

        def compose(urls):
            seen["urls"] = urls
            return (
                "<title>새 글</title>\n"
                '<h1 style="font-size: 20px;">새 글 제목</h1>\n'
                "<p>본문</p>\n"
                f'<p><br></p><div><img src="{urls[0]}" alt="첫 사진"></div>\n'
                f'<div><img src="{urls[1]}" alt="둘째"></div>'
            )

        post = client.publish(
            title="새 글 제목",
            hit=777,
            images=[("a.png", png), ("b.png", png)],
            compose=compose,
        )

    assert post.id == "162"
    assert post.link.endswith("id=162")

    # 서버가 준 주소가 본문에 들어갔고, 업로드 두 번이 일어났습니다.
    assert site.uploads == 2
    assert seen["urls"] == [
        f"{site.base}/files/editor/20260901.jpg",
        f"{site.base}/files/editor/20260902.jpg",
    ]

    saved = site.posts[0]
    assert saved["title"] == "새 글 제목"
    assert saved["hit"] == 777
    assert saved["html_mode"] == "html"
    assert saved["notice"] == "0"
    assert "<title>새 글</title>" in saved["content"]
    assert 'alt="첫 사진"' in saved["content"]
    # 업로드하면서 잠깐 들어갔던 <img> 는 최종 본문에 남지 않습니다 (우리 HTML 의 두 장만).
    assert saved["content"].count("<img") == 2

    # 등록 직전 화면을 남겨 두어 문제가 생기면 볼 수 있습니다.
    assert list(tmp_path.glob("*-before-submit.png"))


def test_wrong_password_fails_with_a_screenshot(site, tmp_path):
    with BoardClient(profile_for(site), USER, "wrong", artifacts=tmp_path) as client:
        with pytest.raises(BoardError, match="로그인에 실패") as info:
            client.login()
    assert "화면:" in str(info.value)
    assert list(tmp_path.glob("*-login-failed.png"))


def test_inspect_dumps_the_form(site, tmp_path):
    with BoardClient(profile_for(site), USER, PASSWORD) as client:
        report_path = client.inspect(tmp_path)

    import json

    report = json.loads(report_path.read_text(encoding="utf-8"))
    names = {f["name"] for f in report["form_fields"]}
    assert {"subject", "hit", "content", "html_type"} <= names
    rows = {f["row"] for f in report["form_fields"] if f["name"] == "subject"}
    assert rows == {"제목"}
    assert report["editor"]["summernote"] is True
    assert "codeview" in report["editor"]["toolbar_buttons"]
    assert (tmp_path / "inspect.json").exists()
    assert any(step["step"] == "write" for step in report["steps"])
