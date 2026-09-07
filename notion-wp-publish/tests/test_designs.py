# -*- coding: utf-8 -*-
"""고객사별 썸네일 디자인 고정."""

from __future__ import annotations

import json

import pytest

from notionwp.designs import Design, DesignError, load, path_for, safe_name, save
from notionwp.thumbnail import Palette

PALETTE = Palette(
    background="#FAF7F1", accent="#C9A15B", title="#463525", sub="#7A6650",
    pill_bg="#F0E6D5", pill_fg="#8A6A3A", brand="#463525", muted="#A2917C",
    rule="#E6DCC9", ornament="#F3ECE0",
)


def design(**kwargs) -> Design:
    base = dict(client="어떤의원", palette=PALETTE, name_en="SOME CLINIC",
                domain="some.co.kr")
    return Design(**{**base, **kwargs})


def test_round_trip(tmp_path):
    save(design(logo=b"\x89PNG fake"), tmp_path)
    back = load("어떤의원", tmp_path)
    assert back is not None
    assert back.palette.background == "#FAF7F1"
    assert back.name_en == "SOME CLINIC"
    assert back.logo == b"\x89PNG fake"


def test_unknown_client_is_none(tmp_path):
    assert load("처음보는의원", tmp_path) is None


def test_an_existing_design_is_never_overwritten_by_accident(tmp_path):
    """굳힌 디자인이 조용히 바뀌면 같은 고객사 썸네일이 달라집니다."""
    save(design(), tmp_path)
    with pytest.raises(DesignError, match="이미 확정"):
        save(design(), tmp_path)


def test_overwrite_is_possible_when_asked(tmp_path):
    save(design(), tmp_path)
    changed = design()
    changed.palette = Palette(**{**PALETTE.__dict__, "background": "#000000"})
    save(changed, tmp_path, overwrite=True)
    assert load("어떤의원", tmp_path).palette.background == "#000000"


def test_a_missing_colour_is_reported(tmp_path):
    save(design(), tmp_path)
    path = path_for("어떤의원", tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["palette"]["accent"]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DesignError, match="accent"):
        load("어떤의원", tmp_path)


def test_a_missing_logo_file_does_not_stop_loading(tmp_path):
    """로고가 사라져도 워드마크로 그릴 수 있으므로 멈추지 않습니다."""
    save(design(logo=b"\x89PNG fake"), tmp_path)
    (tmp_path / "logos" / "어떤의원.png").unlink()
    back = load("어떤의원", tmp_path)
    assert back is not None and back.logo == b""


def test_design_yields_brand_and_fonts(tmp_path):
    save(design(logo=b"\x89PNG fake"), tmp_path)
    back = load("어떤의원", tmp_path)
    brand = back.brand()
    assert brand.name == "어떤의원" and brand.has_logo
    assert back.fonts().hangul_bold  # 저장소에 담아 둔 폰트를 읽어옵니다


def test_path_traversal_in_a_client_name_is_stripped():
    assert "/" not in safe_name("../../etc/passwd")
    assert ".." not in safe_name("..")


def test_skeleton_and_size_survive_a_round_trip(tmp_path):
    """골격과 규격이 고객사마다 다르므로 파일에 함께 굳힙니다."""
    save(design(skeleton="minimal", width=1920, height=1080), tmp_path)
    back = load("어떤의원", tmp_path)
    assert (back.skeleton, back.width, back.height) == ("minimal", 1920, 1080)


def test_older_files_without_a_skeleton_default_to_band(tmp_path):
    import json
    save(design(), tmp_path)
    path = path_for("어떤의원", tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("skeleton", "width", "height"):
        raw.pop(key, None)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    back = load("어떤의원", tmp_path)
    assert (back.skeleton, back.width, back.height) == ("band", 1200, 630)
