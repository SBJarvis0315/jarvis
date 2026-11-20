# -*- coding: utf-8 -*-
"""롱폼 고도화 썸네일 — 대상 고르기와 틀 HTML."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from notionwp.longform_thumb import STYLES, _inline, build_html, eligible, safe_box, wants_longform
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


def test_safe_box_survives_every_site_crop():
    # 지혜로운 필라테스: 1200x900 캔버스를 목록 4:3, 커버 2:1 로 자름 → 세로 가운데 600px 띠
    assert safe_box(1200, 900, (4 / 3, 2.0)) == (0.0, 150.0, 1200.0, 600.0)
    # 잘림이 없으면 캔버스 전체
    assert safe_box(1920, 1080, ()) == (0.0, 0.0, 1920.0, 1080.0)
    # 넓은 캔버스를 4:3 으로 자르면 좌우가 잘림
    x, y, w, h = safe_box(1920, 1080, (4 / 3,))
    assert (round(w), h) == (1440, 1080.0) and round(x) == 240


@pytest.mark.parametrize("style", STYLES)
def test_text_layer_is_placed_inside_the_safe_band(style, tmp_path):
    import re as _re

    bg = tmp_path / "bg.png"
    bg.write_bytes(b"")
    doc, w, h, scale = build_html(style, bg, "윗줄", "제목", canvas=(1200, 900, (4 / 3, 2.0)))
    m = _re.search(r"\.stage\{position:absolute;left:([\d.]+)px;top:([\d.]+)px;width:(\d+)px;height:(\d+)px;"
                   r"transform-origin:0 0;transform:scale\(([\d.]+)\)", doc)
    left, top, w0, h0, s = (float(v) for v in m.groups())
    assert (w, h) == (1200, 900) and round(w * scale) == 1920
    assert top >= 150 - 0.01 and top + h0 * s <= 750 + 0.01
    assert left >= -0.01 and left + w0 * s <= 1200 + 0.01


def test_pilates_longform_style_is_fixed_to_ivory():
    from notionwp.longform_thumb import fixed_style

    assert fixed_style("지혜로운 필라테스") == "ivory"
    assert fixed_style("") == ""
