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


def test_layout_overrides_survive_a_round_trip(tmp_path):
    """레퍼런스마다 로고 크기와 여백이 달라, 골격 치수를 고객사별로 굳힙니다."""
    save(design(skeleton="minimal", layout={"pad_x": 128, "main_size": 155}), tmp_path)
    back = load("어떤의원", tmp_path)
    assert back.layout == {"pad_x": 128.0, "main_size": 155.0}


def test_a_design_without_layout_keeps_the_skeleton_defaults(tmp_path):
    save(design(skeleton="minimal"), tmp_path)
    assert load("어떤의원", tmp_path).layout == {}


# ----------------------------------------------------- 돌아가며 쓰는 모양 (variants)

from notionwp.designs import Variant  # noqa: E402

PALETTE_B = Palette(
    background="#F4F8FC", accent="#F4F8FC", title="#023E8A", sub="#5A7FA8",
    pill_bg="#DCE8F6", pill_fg="#023E8A", brand="#023E8A", muted="#8DB0D1",
    rule="#D0DCEB", ornament="#E3F1F8", domain="#8DB0D1",
)


def test_variants_rotate_by_ordinal_and_wrap():
    """세 모양이면 0,1,2,0,1,2… 순번이 전체 순서를 따라 돌아갑니다."""
    d = design(skeleton="card", variants=[
        Variant("블루", PALETTE), Variant("라이트", PALETTE_B), Variant("네이비", PALETTE),
    ])
    assert [d.pick(i).note for i in range(7)] == ["블루", "라이트", "네이비", "블루", "라이트", "네이비", "블루"]
    assert d.pick(1).palette is PALETTE_B
    # 골라낸 모양은 더 이상 변형을 품지 않습니다 — 렌더에 바로 쓰는 단일 디자인입니다.
    assert d.pick(1).variants == []


def test_a_design_without_variants_picks_itself():
    d = design()
    assert d.pick(0) is d and d.pick(5) is d


def test_a_variant_layers_its_layout_and_shapes_over_the_base():
    d = design(skeleton="card", layout={"pad_x": 60, "bar_h": 6},
               shapes=[{"kind": "band", "top": 528, "color": "#000"}],
               variants=[Variant("라이트", PALETTE_B, layout={"bar_h": 0}, shapes=[{"kind": "circle", "cx": 1, "cy": 1, "d": 2, "color": "#fff"}])])
    chosen = d.pick(0)
    assert chosen.layout == {"pad_x": 60, "bar_h": 0}
    assert chosen.shapes == [{"kind": "circle", "cx": 1, "cy": 1, "d": 2, "color": "#fff"}]


def test_variants_survive_a_round_trip(tmp_path):
    d = design(skeleton="card", variants=[
        Variant("블루", PALETTE, layout={"bar_h": 6}, shapes=[{"kind": "band", "top": 528, "color": "rgba(2,62,138,0.5)"}]),
        Variant("라이트", PALETTE_B),
    ])
    save(d, tmp_path)
    back = load("어떤의원", tmp_path)
    assert [v.name for v in back.variants] == ["블루", "라이트"]
    assert back.variants[0].layout == {"bar_h": 6.0}
    assert back.variants[0].shapes[0]["kind"] == "band"
    assert back.variants[1].palette.domain == "#8DB0D1"
    # 변형이 있는 파일은 첫 변형의 색이 기본 팔레트가 됩니다.
    assert back.palette.background == PALETTE.background


def test_a_variant_missing_a_colour_is_reported(tmp_path):
    body = {"client": "어떤의원", "skeleton": "card", "variants": [{"name": "x", "palette": {"background": "#fff"}}]}
    path_for("어떤의원", tmp_path).write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(DesignError, match="variants\\[0\\]"):
        load("어떤의원", tmp_path)


def test_the_real_clearseoul_file_has_three_rotating_looks():
    d = load("클리어서울안과")
    assert d is not None and d.skeleton == "card" and (d.width, d.height) == (1200, 628)
    assert [v.name for v in d.variants] == ["블루", "라이트", "네이비"]
    assert d.pick(3).note == "블루"
    assert not d.logo  # 로고 없이 글자로 브랜드를 세우는 디자인입니다
