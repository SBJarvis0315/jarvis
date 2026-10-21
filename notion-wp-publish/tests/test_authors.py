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
        assert authors.resolve(wp, Author("c", spec), "c") == 1


def test_resolve_refuses_when_nothing_is_configured_and_lists_candidates():
    with pytest.raises(AuthorError) as err:
        authors.resolve(FakeWordPress(), None, "고객")
    assert "지정되지 않아" in str(err.value)
    assert "테스트 저자" in str(err.value)  # 쓸 수 있는 사용자 안내
    assert "growth-team" not in str(err.value)  # 작업 계정은 후보에서 뺀다


def test_resolve_refuses_the_login_account_and_growth_names():
    wp = FakeWordPress()
    for spec in ("Growth", "growth-team", "2"):
        with pytest.raises(AuthorError):
            authors.resolve(wp, Author("c", spec), "c")


def test_resolve_refuses_an_unknown_user():
    with pytest.raises(AuthorError):
        authors.resolve(FakeWordPress(), Author("c", "없는사람"), "c")


def test_publisher_sets_the_author_on_the_post():
    wp = FakeWordPress()
    Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp).run()
    assert [p["author"] for p in wp.posts.values()] == [1]


def test_publisher_without_an_author_stops_before_creating_anything(monkeypatch):
    from types import SimpleNamespace

    from notionwp import publish as publish_mod

    monkeypatch.setattr(
        publish_mod,
        "authors_mod",
        SimpleNamespace(load=lambda client, directory=None: None, resolve=authors.resolve),
    )
    wp = FakeWordPress()
    pub = Publisher(CONFIG, notion=FakeNotion([complete_page()], sample_page()), wp=wp)
    with pytest.raises(AuthorError):
        pub.run()
    assert wp.posts == {} and wp.media == []
