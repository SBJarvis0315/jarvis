from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import page_with_evidence_table, sample_page
from notionwp.extract import extract
from notionwp.richtext import block_text, strip_markers


def body_texts(blocks) -> list[str]:
    return [block_text(b) for b in blocks]


def test_guide_toggle_is_excluded():
    result = extract(sample_page())
    joined = "\n".join(body_texts(result.body))
    assert "기획안입니다" not in joined
    assert not any(b.get("type") == "toggle" for b in result.body)


def test_notice_callouts_and_meta_description_excluded():
    result = extract(sample_page())
    joined = "\n".join(body_texts(result.body))
    assert "원고 자동화 에이전트" not in joined
    assert "모든 콘텐츠는 하단 토글" not in joined
    # 메타 디스크립션 라벨과 바로 뒤 문단이 함께 빠져야 합니다.
    assert "메타 디스크립션" not in joined
    assert "색소의 깊이와 종류, 피부 상태에 따라 달라집니다" not in joined


def test_h1_is_captured_but_not_in_body():
    result = extract(sample_page())
    assert result.h1.startswith("기미 레이저 몇 회 받아야 할까")
    assert not any(b.get("type") == "heading_1" for b in result.body)


def test_body_starts_at_intro_paragraph_and_keeps_content():
    result = extract(sample_page())
    # H1 바로 뒤 도입 문단부터가 본문입니다.
    assert result.body[0]["type"] == "paragraph"
    assert "정해진 숫자가 아니라" in block_text(result.body[0])
    joined = "\n".join(body_texts(result.body))
    assert "핵심 포인트 7가지" in joined
    assert "클리어톤의원 진료 안내 확인하기" in joined
    assert not result.is_empty


def test_review_sections_are_cut_from_body():
    result = extract(sample_page())
    joined = "\n".join(body_texts(result.body))
    for marker in ("작성 메타 정보", "구조화 제안", "셀프 점검 결과", "사용자 확인 요청"):
        assert marker not in joined
    # 마지막 본문 블록이 클로징 CTA여야 합니다 (뒤따르던 구분선은 잘려나감).
    assert result.body[-1]["type"] != "divider"


def test_review_sections_are_kept_for_later_use():
    result = extract(sample_page())
    names = {strip_markers(n) for n in result.review_sections}
    assert "작성 메타 정보" in names
    assert "구조화 제안" in names


def test_image_hints_parsed_from_structure_suggestion():
    result = extract(sample_page())
    positions = [h.position for h in result.image_hints]
    alts = [h.alt for h in result.image_hints]

    assert positions == ["도입부", "병변 비교표 상단", "회차 설명 섹션", "클로징"]
    assert alts[0] == "기미 레이저 치료 회차를 상담하는 진료 장면"
    # 백틱 밖의 꼬리 주석은 ALT에 들어가면 안 됩니다.
    assert alts[3] == "클리어톤의원 색소 레이저 장비"


def test_schema_hint_parsed():
    result = extract(sample_page())
    assert "FAQPage" in result.schema_hint


def test_bold_paragraph_review_marker_cuts_body():
    result = extract(page_with_evidence_table())
    joined = "\n".join(body_texts(result.body))
    assert "고주파 유전가열" in joined
    assert "근거 자료 표" not in joined
    assert not any(b.get("type") == "table" for b in result.body)


def test_empty_body_is_detected():
    from fixtures import divider, para

    result = extract([para(), divider(), para()])
    assert result.is_empty
