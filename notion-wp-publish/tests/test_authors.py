"""고객사별 글 작성자 지정: 작업 계정(Growth)으로 저자가 찍히지 않게 막는다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fixtures import sample_page  # noqa: E402
from notionwp import authors  # noqa: E402
from notionwp.authors import Author, AuthorError  # noqa: E402
from notionwp.publish import Publisher  # noqa: E402
from test_gate_schema import CONFIG, complete_page  # noqa: E402
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: E402,F401


def test_load_reads_the_file_and_missing_file_is_none(tmp_path):
    (tmp_path / "고객.json").write_text(
        json.dumps({"client": "고객", "author": "이지혜"}, ensure_ascii=False), encoding="utf-8"
    )
    assert authors.load("고객", tmp_path).author == "이지혜"
    assert authors.load("없는고객", tmp_path) is None


def test_load_rejects_an_empty_author(tmp_path):
    (tmp_path / "고객.json").write_text('{"author": " "}', encoding="utf-8")
    with pytest.raises(AuthorError):
        authors.load("고객", tmp_path)


def test_resolve_returns_the_user_id_by_name_slug_or_id():
    wp = FakeWordPress()
    for spec in ("테스트 저자", "author", "1"):
        choice = authors.resolve(wp, Author("c", spec), "c")
        assert (choice.user_id, choice.warning) == (1, "")


def test_resolve_picks_a_non_growth_user_automatically_without_a_file():
    # 로그인 계정이 Growth 라서 제외되고, 남은 사용자(id 1)가 저자가 된다.
    assert authors.resolve(FakeWordPress(), None, "고객").user_id == 1


def test_resolve_prefers_the_login_account_when_it_is_not_growth():
    wp = FakeWordPress()
    wp.USERS = [  # 첫 항목이 로그인 계정이다
        {"id": 2, "name": "클리어톤의원 대표원장", "slug": "cleartone"},
        {"id": 1, "name": "yuri", "slug": "yuri"},
    ]
    assert authors.resolve(wp, None, "고객").user_id == 2  # 로그인 계정(id 2) 우선


def test_resolve_falls_back_to_the_lowest_id_when_login_is_growth():
    wp = FakeWordPress()
    wp.USERS = [  # 첫 항목이 로그인 계정이다
        {"id": 2, "name": "Growth", "slug": "growth-team"},
        {"id": 3, "name": "yuri park", "slug": "yuri-park"},
        {"id": 1, "name": "이지혜", "slug": "yuri"},
    ]
    assert authors.resolve(wp, None, "고객").user_id == 1


def test_resolve_uses_the_login_account_with_a_warning_when_only_growth_exists():
    wp = FakeWordPress()
    wp.USERS = [{"id": 2, "name": "Growth", "slug": "growth-team"}]
    choice = authors.resolve(wp, None, "고객")
    assert choice.user_id == 2  # 멈추지 않고 로그인 계정으로
    assert "Growth 로 보입니다" in choice.warning


def test_resolve_falls_back_with_a_warning_for_a_bad_explicit_author():
    wp = FakeWordPress()
    for spec in ("Growth", "2", "없는사람"):
        choice = authors.resolve(wp, Author("c", spec), "c")
        assert choice.user_id == 1  # 자동 선택(Growth 가 아닌 사용자)
        assert "자동으로 골랐습니다" in choice.warning


def test_publisher_sets_the_author_on_the_post():
    wp = FakeWordPress()
    Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp).run()
    assert [p["author"] for p in wp.posts.values()] == [1]


def test_publisher_picks_an_author_automatically_without_a_file(monkeypatch):
    from types import SimpleNamespace

    from notionwp import publish as publish_mod

    monkeypatch.setattr(
        publish_mod,
        "authors_mod",
        SimpleNamespace(load=lambda client, directory=None: None, resolve=authors.resolve),
    )
    wp = FakeWordPress()
    Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp).run()
    assert [p["author"] for p in wp.posts.values()] == [1]  # Growth(id 2)가 아니다


def test_publisher_does_not_stop_when_only_growth_exists(monkeypatch):
    from types import SimpleNamespace

    from notionwp import publish as publish_mod

    monkeypatch.setattr(
        publish_mod,
        "authors_mod",
        SimpleNamespace(load=lambda client, directory=None: None, resolve=authors.resolve),
    )
    wp = FakeWordPress()
    wp.USERS = [{"id": 2, "name": "Growth", "slug": "growth-team"}]
    pub = Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp)
    outcomes = pub.run()
    assert [p["author"] for p in wp.posts.values()] == [2]
    assert any("Growth 로 보입니다" in w for w in outcomes[0].warnings)  # 로그에 경고가 남는다
