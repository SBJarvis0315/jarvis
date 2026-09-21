# -*- coding: utf-8 -*-
"""글 맨 끝에 늘 붙는 고정 블록.

참포도나무병원 숏폼은 본문 아래에 의료진 프로필 패턴이 항상 들어갑니다.
원고 생성으로는 할 수 없는 일이라(원고에 적은 마크업은 이스케이프됩니다)
발행 단계가 붙입니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp.tail import Tail, TailError, append, load, path_for

PATTERN = '<!-- wp:block {"ref":2246} /-->'


def write(tmp_path, **body) -> Path:
    base = {"client": "어떤의원", "types": ["숏폼"], "blocks": PATTERN}
    path = path_for("어떤의원", tmp_path)
    path.write_text(json.dumps({**base, **body}, ensure_ascii=False), encoding="utf-8")
    return path


def test_no_file_means_nothing_is_appended(tmp_path):
    assert load("어떤의원", tmp_path) is None
    assert append("본문", None, "숏폼") == "본문"


def test_it_is_appended_raw_not_escaped(tmp_path):
    write(tmp_path)
    out = append("<!-- wp:paragraph -->\n<p>끝</p>\n<!-- /wp:paragraph -->",
                 load("어떤의원", tmp_path), "숏폼")
    # 블록 주석이 글자로 바뀌면 안 됩니다. 그러면 독자에게 마크업이 보입니다.
    assert out.endswith(PATTERN)
    assert "&lt;" not in out


def test_only_the_listed_types_get_it(tmp_path):
    write(tmp_path)
    tail = load("어떤의원", tmp_path)
    assert tail.applies_to("숏폼")
    assert not tail.applies_to("롱폼")
    assert append("본문", tail, "롱폼") == "본문"


def test_an_empty_type_list_means_every_type(tmp_path):
    write(tmp_path, types=[])
    tail = load("어떤의원", tmp_path)
    assert tail.applies_to("숏폼") and tail.applies_to("롱폼")


def test_an_empty_blocks_value_is_reported_not_silently_ignored(tmp_path):
    write(tmp_path, blocks="   ")
    with pytest.raises(TailError, match="blocks"):
        load("어떤의원", tmp_path)


def test_a_broken_file_is_reported(tmp_path):
    path_for("어떤의원", tmp_path).write_text("{ 망가진", encoding="utf-8")
    with pytest.raises(TailError):
        load("어떤의원", tmp_path)


def test_the_real_champodonamu_file_is_shortform_only():
    """저장소에 확정해 둔 파일이 의도대로인지 함께 지킵니다."""
    tail = load("참포도나무병원")
    assert tail is not None
    assert tail.types == ["숏폼"]
    assert '"ref":2246' in tail.blocks
    assert "is-style-dots" in tail.blocks
