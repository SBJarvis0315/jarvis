# -*- coding: utf-8 -*-
"""롱폼 고도화 썸네일 — 대상 고르기와 틀 HTML."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from notionwp.longform_thumb import STYLES, _inline, build_html, eligible, wants_longform
from notionwp.registry import build_config, load_defaults

DEFAULTS = load_defaults()


def _registry(thumbs):
    props = {
        "고객사": {"type": "title", "title": [{"plain_text": "제로클리닉"}]},
        "상태": {"type": "select", "select": {"name": "활성"}},
        "플래너 DB ID": {"type": "rich_text", "rich_text": [{"plain_text": "5ec68fa206ff8312ad80878accfa81b4"}]},
        "썸네일": {"type": "multi_select", "multi_select": [{"name": n} for n in thumbs]},
    }
    return {"properties": props}


def _row(kind="롱폼", title="리투오 부작용｜정상 범위", thumb=False):
    return {
        "유형": {"type": "select", "select": {"name": kind}},
        "제목": {"type": "title", "title": [{"plain_text": title}]},
        "썸네일": {"type": "files", "files": [{"name": "t.png"}] if thumb else []},
    }


def cfg_with(*thumbs):
    cfg, reason = build_config(DEFAULTS, _registry(list(thumbs)), platform=None)
    assert cfg, reason
    return cfg


def test_only_clients_with_longform_in_thumbnail_column():
    assert wants_longform(cfg_with("롱폼", "숏폼"))
    assert not wants_longform(cfg_with("숏폼"))
    assert not wants_longform(cfg_with())
    assert not wants_longform(replace(cfg_with("롱폼"), thumbnail_types=None))


def test_only_empty_longform_rows_with_real_titles():
    cfg = cfg_with("롱폼")
    assert eligible(_row(), cfg)[0]
    assert not eligible(_row(kind="숏폼"), cfg)[0]
    assert not eligible(_row(thumb=True), cfg)[0]
    assert not eligible(_row(title="롱폼 템플릿"), cfg)[0]
    assert not eligible(_row(title=""), cfg)[0]


def test_inline_escapes_html_and_bolds_marked_words():
    assert _inline("<b>x</b> **리투오**") == "&lt;b&gt;x&lt;/b&gt; <b>리투오</b>"
    assert _inline("두 줄\\n제목") == "두 줄<br>제목"


@pytest.mark.parametrize("style", STYLES)
def test_every_style_builds_with_both_lines(style, tmp_path):
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"")  # 색 샘플링은 실패해도 기본색으로 넘어가야 합니다
    doc, w, h, scale = build_html(style, bg, "윗줄 문구", "큰 제목", pill="분류", brand="OO 법률사무소")
    assert "윗줄 문구" in doc and "큰 제목" in doc
    assert round(w * scale) == 1920


def test_unknown_style_is_refused(tmp_path):
    with pytest.raises(ValueError):
        build_html("fancy", Path(tmp_path / "x.png"), "a", "b")
