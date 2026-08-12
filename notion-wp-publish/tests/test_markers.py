"""원고 본문의 `::IMG-01::` 이미지 마커 처리.

원고 자동화 에이전트가 이미지 자리를 마커로 표시합니다. 이 문자열이
발행 본문에 그대로 나가면 안 되고, 위치는 배치 기준으로 써야 합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import block, divider, h2, h3, para, rt
from notionwp.extract import extract, parse_marker
from notionwp.gutenberg import render
from notionwp.plan import PagePlan
from notionwp.publish import Publisher
from test_gate_schema import CONFIG, complete_page
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: F401


def marked_page():
    return [
        block("toggle", rt("콘텐츠 가이드")),
        para("메타 디스크립션", bold=True),
        para("설명문입니다."),
        para('::THUMB:: alt="대표 이미지 후보" 설명="메타 아래 배치"'),
        block("heading_1", rt("삼성역 색소 치료 피부과 고르는 기준")),
        para("도입 문단입니다."),
        para('::IMG-01:: alt="진료 상담 장면" 설명="도입부 직후"'),
        h2("색소 치료 피부과에서 결과가 달라지는 이유"),
        para("본문 문단."),
        para('::IMG-02:: alt="병변 비교 자료" 설명="비교 설명 뒤"'),
        h3("병변 종류"),
        para("세부 설명."),
        divider(),
        h2("📋 작성 메타 정보"),
        para("검수용"),
    ]


# ------------------------------------------------------------------ 파싱


def test_parse_marker_variants():
    assert parse_marker('::IMG-01:: alt="가" 설명="나"') == (1, "가", "나")
    assert parse_marker('::IMG-12:: alt="가"') == (12, "가", "")
    assert parse_marker('::THUMB:: alt="대표"') == (None, "대표", "")
    # 공백·대소문자 흔들림 허용
    assert parse_marker(':: img - 3 ::  alt="가"') == (3, "가", "")
    # 마커가 아닌 문장은 건드리지 않습니다
    assert parse_marker("본문 문장입니다") is None
    assert parse_marker("코드에서 :: 를 쓰는 문장") is None


# ------------------------------------------------------------------ 본문 제거


def test_markers_are_removed_from_body():
    result = extract(marked_page())
    joined = "\n".join(
        b.get(b.get("type", ""), {}).get("rich_text", [{}])[0].get("plain_text", "")
        if b.get("type") == "paragraph"
        else ""
        for b in result.body
    )
    assert "::IMG" not in joined
    assert "::THUMB" not in joined
    assert "도입 문단입니다." in joined


def test_markers_never_reach_wordpress():
    out = render(extract(marked_page()).body)
    assert "::IMG" not in out
    assert "::THUMB" not in out
    assert 'alt="진료 상담 장면"' not in out  # 마커의 alt 도 본문에 새면 안 됩니다
    assert "색소 치료 피부과에서 결과가 달라지는 이유" in out


# ------------------------------------------------------------------ 위치 기록


def test_marker_positions_are_recorded():
    result = extract(marked_page())
    body_markers = [m for m in result.markers if not m.is_thumbnail]

    assert [m.number for m in body_markers] == [1, 2]
    assert [m.alt_hint for m in body_markers] == ["진료 상담 장면", "병변 비교 자료"]
    assert [m.note for m in body_markers] == ["도입부 직후", "비교 설명 뒤"]

    # 마커를 걷어낸 뒤 본문 기준 위치여야 합니다.
    for m in body_markers:
        assert 0 <= m.index <= len(result.body)


def test_thumbnail_marker_is_separated():
    result = extract(marked_page())
    thumbs = [m for m in result.markers if m.is_thumbnail]
    assert len(thumbs) == 1
    assert thumbs[0].alt_hint == "대표 이미지 후보"


def test_marker_index_points_after_the_preceding_paragraph():
    result = extract(marked_page())
    first = next(m for m in result.markers if m.number == 1)
    # IMG-01 은 도입 문단 바로 뒤, 첫 H2 앞이어야 합니다.
    before = result.body[first.index - 1]
    assert "도입 문단" in before["paragraph"]["rich_text"][0]["plain_text"]


# ------------------------------------------------------------------ 배치 연동


def test_prepare_uses_marker_positions_and_hints(tmp_path):
    page = complete_page()
    notion = FakeNotion([page], marked_page())
    pub = Publisher(CONFIG, notion=notion, wp=FakeWordPress())

    pub.prepare(tmp_path)
    plan = PagePlan.load(next(tmp_path.iterdir()))

    assert len(plan.images) == 2
    assert [i.anchor for i in plan.images] == [
        m.index for m in extract(marked_page()).markers if not m.is_thumbnail
    ]
    # 마커의 문구가 ALT 작성 참고용으로 전달되어야 합니다.
    assert plan.images[0].hint == "진료 상담 장면"
    assert plan.images[1].hint == "병변 비교 자료"
    # ALT 자체는 여전히 비어 있어야 합니다 (이미지를 보고 써야 하므로).
    assert all(i.alt == "" for i in plan.images)


def test_falls_back_to_even_spread_without_markers(tmp_path):
    from fixtures import sample_page

    notion = FakeNotion([complete_page()], sample_page())
    pub = Publisher(CONFIG, notion=notion, wp=FakeWordPress())

    pub.prepare(tmp_path)
    plan = PagePlan.load(next(tmp_path.iterdir()))

    assert len(plan.images) == 2
    assert all(i.hint == "" for i in plan.images)
    assert plan.images[0].anchor != plan.images[1].anchor
