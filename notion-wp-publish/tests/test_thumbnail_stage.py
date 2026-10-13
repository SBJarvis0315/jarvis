# -*- coding: utf-8 -*-
"""썸네일 단계 — 어떤 행에 썸네일을 만들지 고르는 규칙."""

from __future__ import annotations

from dataclasses import replace

from notionwp.registry import build_config, load_defaults
from notionwp.thumbnails import eligible, has_file

DEFAULTS = load_defaults()


def registry_row(**over) -> dict:
    values = {
        "고객사": "클리어톤의원",
        "상태": "활성",
        "플래너 DB ID": "5ec68fa206ff8312ad80878accfa81b4",
        "대상 유형": "롱폼, 숏폼",
        "워드프레스 주소": "https://blog.cleartone.co.kr",
        "유튜브 채널": "",
    }
    unknown = set(over) - set(values)
    assert not unknown, f"설정표에 없는 컬럼: {unknown}"
    values.update(over)

    props: dict = {}
    for key, val in values.items():
        if key == "상태":
            props[key] = {"select": {"name": val}} if val else {"select": None}
        else:
            props[key] = {"rich_text": [{"plain_text": val}]} if val else {"rich_text": []}
    return {"properties": props}


CONFIG, _ = build_config(DEFAULTS, registry_row())


def row(title="레이저토닝 | 관리 총정리", kind="숏폼", thumb=False, keywords="레이저토닝"):
    props = {
        "제목": {"title": [{"plain_text": title}]} if title else {"title": []},
        "유형": {"select": {"name": kind}} if kind else {"select": None},
        "썸네일": {"files": [{"name": "a.png"}] if thumb else []},
        "키워드": {"rich_text": [{"plain_text": keywords}]} if keywords else {"rich_text": []},
    }
    return props


def test_a_shortform_row_without_a_thumbnail_qualifies():
    ok, reason = eligible(row(), CONFIG)
    assert ok, reason


def test_an_existing_thumbnail_is_never_replaced():
    """사람이 올린 썸네일을 덮어쓰면 안 됩니다."""
    ok, reason = eligible(row(thumb=True), CONFIG)
    assert not ok and "이미" in reason


def test_a_template_title_is_not_a_real_title():
    """제목이 템플릿 이름 그대로면 원고 생성이 아직 안 돈 것입니다."""
    ok, reason = eligible(row(title="템플릿(엔티티/롱폼/네이버) 2"), CONFIG)
    assert not ok and "템플릿" in reason


def test_a_template_word_anywhere_in_the_title_blocks_it():
    ok, _ = eligible(row(title="복제본 템플릿 3"), CONFIG)
    assert not ok


def test_an_empty_title_is_skipped():
    ok, reason = eligible(row(title=""), CONFIG)
    assert not ok and "제목" in reason


def test_only_the_listed_types_are_made():
    """당장은 숏폼만 만듭니다."""
    ok, reason = eligible(row(kind="롱폼"), CONFIG)
    assert not ok and "유형" in reason


def test_widening_the_types_lets_other_kinds_through():
    ok, _ = eligible(row(kind="롱폼"), CONFIG, types=("숏폼", "롱폼"))
    assert ok


def test_a_row_with_no_type_is_skipped():
    ok, _ = eligible(row(kind=""), CONFIG)
    assert not ok


def test_missing_keywords_do_not_block_a_row():
    """뱃지가 비는 것뿐이라 썸네일은 만들 수 있습니다."""
    ok, _ = eligible(row(keywords=""), CONFIG)
    assert ok


def test_has_file_reads_the_notion_shape():
    assert has_file({"files": [{"name": "a.png"}]})
    assert not has_file({"files": []})
    assert not has_file(None)


# --------------------------------------------------- 설정표: 워드프레스 없는 고객사

def test_a_client_without_wordpress_is_still_a_thumbnail_target():
    cfg, reason = build_config(
        DEFAULTS, registry_row(**{"워드프레스 주소": ""}), require_wordpress=False
    )
    assert cfg is not None, reason
    assert cfg.client == "클리어톤의원"


def test_that_same_client_is_not_a_publish_target():
    cfg, reason = build_config(DEFAULTS, registry_row(**{"워드프레스 주소": ""}))
    assert cfg is None and "원고 생성 전용" in reason


# ------------------------------------------------- 돌아가며 쓰는 모양의 순번

from notionwp.thumbnails import rotation_order  # noqa: E402


def _row(rid, created, kind="숏폼", thumb=False):
    # row() 는 속성만 돌려줍니다. 순번은 행 전체(id·created_time)가 필요합니다.
    return {"id": rid, "created_time": created, "properties": row(kind=kind, thumb=thumb)}


def test_rotation_follows_creation_order_within_the_type():
    rows = [
        _row("c", "2026-10-03T00:00:00Z"),
        _row("a", "2026-10-01T00:00:00Z", thumb=True),   # 이미 썸네일이 있어도 순번은 셉니다
        _row("x", "2026-10-02T00:00:00Z", kind="롱폼"),    # 다른 유형은 끼지 않습니다
        _row("b", "2026-10-02T00:00:00Z"),
    ]
    assert rotation_order(rows, CONFIG) == {"a": 0, "b": 1, "c": 2}


def test_rotation_is_stable_across_runs():
    """회차마다 몇 건을 만들든 전체 순서가 같아야 '돌아가며' 가 이어집니다."""
    rows = [_row(str(i), f"2026-10-{i + 1:02d}T00:00:00Z") for i in range(5)]
    first = rotation_order(rows, CONFIG)
    rows[0]["properties"]["썸네일"] = {"type": "files", "files": [{"name": "t.png"}]}
    assert rotation_order(rows, CONFIG) == first
