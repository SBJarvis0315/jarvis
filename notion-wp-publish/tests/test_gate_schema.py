from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.config import Config
from notionwp.extract import extract
from notionwp.publish import check_body, check_properties
from notionwp.schema import build_schemas, extract_faqs

CONFIG = Config.load(Path(__file__).resolve().parents[1] / "config" / "cleartone.json")
TODAY = date(2026, 8, 12)


def file_prop(*names: str) -> dict:
    return {
        "type": "files",
        "files": [
            {"name": n, "type": "file", "file": {"url": f"https://s3.test/{n}"}} for n in names
        ],
    }


def text_prop(value: str) -> dict:
    return {"type": "rich_text", "rich_text": [{"plain_text": value, "annotations": {}}]}


def complete_page(**overrides) -> dict:
    props = {
        "제목": {"type": "title", "title": [{"plain_text": "기미 레이저 몇 회", "annotations": {}}]},
        "진행 상황": {"type": "status", "status": {"name": "컨펌 진행 중"}},
        "유형": {"type": "select", "select": {"name": "롱폼"}},
        "발행 예정일": {"type": "date", "date": {"start": "2026-08-11"}},
        "썸네일": file_prop("thumb.png"),
        "본문 이미지": file_prop("a.jpg", "b.jpg"),
        "메타타이틀": text_prop("기미 레이저 횟수 | 클리어톤의원"),
        "메타디스크립션": text_prop("기미 레이저 횟수는 색소의 깊이에 따라 달라집니다."),
        "슬러그": text_prop("melasma-laser-sessions"),
        "키워드": text_prop("기미 레이저 횟수, 기미 레이저 효과"),
        "카테고리": {"type": "select", "select": {"name": "색소 이야기"}},
        "URL": {"type": "url", "url": ""},
    }
    props.update(overrides)
    return {"id": "e2868fa2-06ff-8387-a4ce-018c082c51d5", "properties": props}


# ------------------------------------------------------------------------ 게이트


def test_complete_row_passes():
    cand = check_properties(CONFIG, complete_page(), on=TODAY)
    assert cand.ok, cand.reasons


def test_status_must_be_confirm_in_progress():
    page = complete_page(**{"진행 상황": {"type": "status", "status": {"name": "작성중"}}})
    cand = check_properties(CONFIG, page, on=TODAY)
    assert not cand.ok
    assert any("진행 상황" in r for r in cand.reasons)


def test_future_publish_date_is_not_published_yet():
    page = complete_page(**{"발행 예정일": {"type": "date", "date": {"start": "2026-08-20"}}})
    cand = check_properties(CONFIG, page, on=TODAY)
    assert any("아직 오지 않음" in r for r in cand.reasons)


def test_publish_date_on_today_passes():
    page = complete_page(**{"발행 예정일": {"type": "date", "date": {"start": "2026-08-12"}}})
    assert check_properties(CONFIG, page, on=TODAY).ok


def test_missing_publish_date_is_blocked():
    page = complete_page(**{"발행 예정일": {"type": "date", "date": None}})
    cand = check_properties(CONFIG, page, on=TODAY)
    assert any("발행 예정일이 비어" in r for r in cand.reasons)


def test_each_required_field_blocks_on_its_own():
    cases = {
        "썸네일": ({"type": "files", "files": []}, "썸네일"),
        "본문 이미지": ({"type": "files", "files": []}, "본문 이미지"),
        "메타타이틀": (text_prop(""), "메타타이틀"),
        "메타디스크립션": (text_prop(""), "메타디스크립션"),
        "슬러그": (text_prop(""), "슬러그"),
    }
    for field, (value, label) in cases.items():
        cand = check_properties(CONFIG, complete_page(**{field: value}), on=TODAY)
        assert not cand.ok, f"{field} 가 비었는데 통과했습니다"
        assert any(label in r for r in cand.reasons)


def test_empty_title_is_blocked():
    page = complete_page(**{"제목": {"type": "title", "title": []}})
    cand = check_properties(CONFIG, page, on=TODAY)
    assert any("제목" in r for r in cand.reasons)


def test_type_outside_filter_is_skipped():
    page = complete_page(**{"유형": {"type": "select", "select": {"name": "네이버"}}})
    cand = check_properties(CONFIG, page, on=TODAY)
    assert any("유형" in r for r in cand.reasons)


def test_partial_completion_never_passes():
    """조건 일부만 맞는 행은 발행 대상이 아니라는 요구사항 2번의 핵심."""
    page = complete_page(**{"슬러그": text_prop(""), "썸네일": {"type": "files", "files": []}})
    cand = check_properties(CONFIG, page, on=TODAY)
    assert not cand.ok
    assert len(cand.reasons) == 2


def test_body_gate_rejects_guide_only_page():
    from fixtures import block, para, rt

    notice = "모든 콘텐츠는 하단 토글(▶)을 열어 콘텐츠 가이드를 확인한 후 작성해주시기 바랍니다."
    guide_only = [
        block("callout", rt(notice)),
        block("toggle", rt("콘텐츠 가이드"), children=[para("기획안 내용")]),
    ]
    cand = check_body(check_properties(CONFIG, complete_page(), on=TODAY), guide_only)
    assert not cand.ok
    assert any("발행할 원고가 없음" in r for r in cand.reasons)


def test_body_gate_accepts_real_manuscript():
    cand = check_body(check_properties(CONFIG, complete_page(), on=TODAY), sample_page())
    assert cand.ok, cand.reasons


# ------------------------------------------------------------------------ 스키마


def test_faqs_extracted_with_numbering_stripped():
    faqs = extract_faqs(extract(sample_page()).body)
    assert len(faqs) == 2
    assert faqs[0]["question"] == "기미 레이저는 몇 번 받아야 효과를 기대할 수 있나요?"
    assert "병변의 깊이와 피부 상태에 따라 다릅니다." in faqs[0]["answer"]


def test_schemas_are_blogposting_and_faqpage_only():
    body = extract(sample_page()).body
    schemas = build_schemas(
        body=body,
        headline="기미 레이저 횟수 | 클리어톤의원",
        description="설명",
        permalink="https://cleartone.co.kr/melasma-laser-sessions/",
        published_iso="2026-08-12T09:00:00+09:00",
        image_url="https://cleartone.co.kr/wp-content/uploads/thumb.png",
        keywords="기미 레이저 횟수, 기미 레이저 효과",
        publisher_name="클리어톤의원",
        author_name="클리어톤의원",
    )

    types = [s["@type"] for s in schemas]
    # 가이드 기준: Article 은 쓰지 않고 BlogPosting + FAQPage 두 가지만.
    assert types == ["BlogPosting", "FAQPage"]
    assert "Article" not in types

    blog = schemas[0]
    assert blog["mainEntityOfPage"]["@id"].endswith("/melasma-laser-sessions/")
    assert blog["keywords"] == "기미 레이저 횟수, 기미 레이저 효과"
    assert blog["publisher"]["name"] == "클리어톤의원"

    faq = schemas[1]
    assert len(faq["mainEntity"]) == 2
    assert faq["mainEntity"][0]["acceptedAnswer"]["@type"] == "Answer"


def test_faqpage_omitted_when_no_faq_section():
    from fixtures import h2, para

    schemas = build_schemas(
        body=[h2("본문"), para("FAQ 섹션이 없는 원고입니다.")],
        headline="제목",
        description="설명",
        permalink="https://cleartone.co.kr/x/",
        published_iso="2026-08-12T09:00:00+09:00",
    )
    assert [s["@type"] for s in schemas] == ["BlogPosting"]
