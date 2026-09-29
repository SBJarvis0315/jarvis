# -*- coding: utf-8 -*-
"""플래너 '게시판' → 워드프레스 글 종류.

개발사가 '용어사전' 같은 별도 글 종류를 만들어 둔 사이트가 있습니다
(비컴성형외과 glossary). 메뉴는 일반 카테고리와 똑같이 생겼지만 속이 달라,
일반 글로 올리면 그 섹션에 들어가지 않습니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notionwp.posttype import DEFAULT, PostTypeError, load, path_for, target_for


def write(tmp_path, boards) -> None:
    path_for("어떤의원", tmp_path).write_text(
        json.dumps({"client": "어떤의원", "boards": boards}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_no_file_means_ordinary_posts(tmp_path):
    assert load("어떤의원", tmp_path) is None
    assert target_for(None, "무엇이든").posts_path == "/wp/v2/posts"


def test_a_mapped_board_goes_to_its_own_post_type(tmp_path):
    write(tmp_path, {"용어사전": {"rest_base": "glossary",
                                  "taxonomy_rest_base": "glossary_cat"}})
    target = target_for(load("어떤의원", tmp_path), "용어사전")

    assert target.posts_path == "/wp/v2/glossary"
    assert target.taxonomy_path == "/wp/v2/glossary_cat"
    # 분류를 담는 필드 이름도 달라집니다. categories 로 보내면 조용히 무시됩니다.
    assert target.taxonomy_field == "glossary_cat"


def test_an_unmapped_board_still_goes_to_ordinary_posts(tmp_path):
    write(tmp_path, {"용어사전": {"rest_base": "glossary"}})
    routing = load("어떤의원", tmp_path)

    for board in ("블로그", "", "없는 게시판"):
        assert target_for(routing, board) == DEFAULT, board


def test_a_mapping_without_rest_base_is_reported(tmp_path):
    write(tmp_path, {"용어사전": {"taxonomy_rest_base": "glossary_cat"}})
    with pytest.raises(PostTypeError, match="rest_base"):
        load("어떤의원", tmp_path)


def test_the_real_becomeps_file_routes_the_glossary():
    """저장소에 확정해 둔 대응표가 의도대로인지 함께 지킵니다."""
    routing = load("비컴성형외과")
    assert routing is not None

    glossary = target_for(routing, "용어사전")
    assert (glossary.rest_base, glossary.taxonomy_rest_base) == ("glossary", "glossary_cat")
    # 용어사전 외의 게시판은 건드리지 않습니다.
    assert target_for(routing, "블로그") == DEFAULT
