# -*- coding: utf-8 -*-
"""썸네일 생성 — 제목 분할 규칙과 조판."""

from __future__ import annotations

import pytest

from notionwp.brand import Brand
from notionwp.thumbnail import (
    Fonts,
    Palette,
    ThumbnailError,
    badge_text,
    build_html,
    render,
    split_title,
)

CLIENT = "클리어톤의원"


# --------------------------------------------------------------- 제목 분할

@pytest.mark.parametrize(
    "title,main,sub",
    [
        # 세로바가 팀이 의도한 경계입니다.
        ("기미 레이저 가격 | 강남 기준 시술별 비용·포함 항목 총정리",
         "기미 레이저 가격", "강남 기준 시술별 비용·포함 항목 총정리"),
        ("피코레이저 vs 일반 색소 레이저 | 원리·효과·적합 케이스 비교 가이드",
         "피코레이저 vs 일반 색소 레이저", "원리·효과·적합 케이스 비교 가이드"),
        # 세로바가 물음표보다 우선합니다.
        ("오타모반이란? | 일반 색소침착과 차이·난치성 색소 치료 기준",
         "오타모반이란?", "일반 색소침착과 차이·난치성 색소 치료 기준"),
        # 세로바가 없으면 물음표 뒤에서 자르고, 부호는 앞토막에 남깁니다.
        ("올타이트 리프팅이란? 울쎄라와 원리·통증·유지기간 차이 총정리",
         "올타이트 리프팅이란?", "울쎄라와 원리·통증·유지기간 차이 총정리"),
        # 서브 안의 물음표는 경계가 아닙니다 — 세로바가 먼저 걸립니다.
        ("레이저토닝 | 시술 후 세안·화장 언제부터? 관리 총정리",
         "레이저토닝", "시술 후 세안·화장 언제부터? 관리 총정리"),
    ],
)
def test_splits_at_the_intended_boundary(title, main, sub):
    assert split_title(title, CLIENT) == (main, sub)


def test_middle_dot_is_not_a_boundary():
    """'·' 는 서브 타이틀 안에서 나열 기호로 쓰입니다. 여기서 자르면 안 됩니다."""
    main, sub = split_title("올타이트 리프팅이란? 울쎄라와 원리·통증·유지기간 차이 총정리", CLIENT)
    assert "·" in sub
    assert main == "올타이트 리프팅이란?"


def test_no_separator_falls_back_to_client_name():
    """구분자가 없으면 제목 전체가 메인이고, 서브는 고객사명으로 채웁니다."""
    assert split_title("클리어톤의원은 어떤 곳인가요?", CLIENT) == (
        "클리어톤의원은 어떤 곳인가요?",
        CLIENT,
    )


def test_trailing_question_mark_is_not_a_split():
    """물음표가 끝에 있으면 뒤에 남는 게 없으므로 자르지 않습니다."""
    main, _ = split_title("검버섯일까요?", CLIENT)
    assert main == "검버섯일까요?"


def test_whitespace_is_normalised():
    assert split_title("  기미   레이저  |   횟수  정리 ", CLIENT) == (
        "기미 레이저",
        "횟수 정리",
    )


def test_empty_title():
    assert split_title("", CLIENT) == ("", "")


def test_bare_hangul_jamo_bar_also_splits():
    """'|' 대신 한글 자모 'ㅣ'가 섞여 들어오는 일이 잦습니다."""
    assert split_title("기미 레이저 ㅣ 횟수 정리", CLIENT) == ("기미 레이저", "횟수 정리")


# --------------------------------------------------------------- 조판

def test_wordmark_stands_in_when_there_is_no_logo():
    brand = Brand(name=CLIENT, name_en="CLEARTONE CLINIC")
    html = build_html("기미 레이저", "횟수 정리", brand, Fonts())
    assert 'class="wordmark"' in html
    assert CLIENT in html and "CLEARTONE CLINIC" in html


def test_logo_is_embedded_when_present():
    brand = Brand(name=CLIENT, logo=b"\x89PNG\r\n\x1a\n fake", logo_mime="image/png")
    html = build_html("기미 레이저", "횟수 정리", brand, Fonts())
    assert "data:image/png;base64," in html
    # 'wordmark' 는 CSS 에 항상 있으므로 요소가 실제로 그려졌는지를 봅니다.
    assert 'class="wordmark"' not in html


def test_empty_sub_omits_the_element():
    html = build_html("기미 레이저", "", Brand(name=CLIENT), Fonts())
    assert 'class="sub"' not in html


def test_markup_in_a_title_cannot_break_the_page():
    html = build_html("<script>alert(1)</script>", "", Brand(name=CLIENT), Fonts())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_refuses_an_empty_title():
    with pytest.raises(ThumbnailError):
        render("", "", Brand(name=CLIENT), Fonts())


# --------------------------------------------------------------- 파생 색

def test_dark_brand_colour_becomes_the_background():
    p = Palette.derive("#2B4FC7")
    assert p.background == "#2B4FC7"
    assert p.title == "#FFFFFF"


def test_light_brand_colour_is_laid_down_faintly():
    """밝은 브랜드 컬러를 그대로 배경에 깔면 흰 글씨가 안 보입니다."""
    p = Palette.derive("#7EC8F0")
    assert p.background != "#7EC8F0"
    assert p.title != "#FFFFFF"


# --------------------------------------------------------------- 뱃지

def test_badge_takes_the_main_keyword():
    assert badge_text("기미 레이저, 기미 레이저 횟수, 강남 기미") == "기미 레이저"


def test_badge_is_dropped_when_the_keyword_is_too_long():
    assert badge_text("레이저토닝 후 세안 언제부터 가능한가요") == ""


def test_badge_survives_an_empty_keyword_field():
    assert badge_text("") == ""


def test_a_client_palette_overrides_the_derived_one():
    """고객사 전용 디자인이 있으면 브랜드 컬러에서 색을 파생하지 않습니다."""
    warm = Palette(
        background="#FAF7F1", accent="#C9A15B", title="#463525", sub="#7A6650",
        pill_bg="#F0E6D5", pill_fg="#8A6A3A", brand="#463525", muted="#A2917C",
        rule="#E6DCC9", ornament="#F3ECE0",
    )
    html = build_html("기미 레이저", "횟수 정리", Brand(name=CLIENT, color="#2B4FC7"),
                      Fonts(), palette=warm)
    assert "#FAF7F1" in html
    assert "#2B4FC7" not in html
