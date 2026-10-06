"""자체 게시판용 HTML — 팀이 손으로 올리던 형식을 그대로 내는지."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import block, bullet, h2, h3, para, rt
from notionwp.boardhtml import H1_STYLE, H2_STYLE, H3_STYLE, render, render_blocks
from notionwp.gutenberg import image_block


def test_head_block_matches_the_published_article():
    html = render(
        [para("첫 문단")],
        title="신사다이어트 발목 살 빼는 법｜종아리·발목 라인 관리 가이드",
        meta_title="발목 살 빼는 법 | 제로클리닉",
        meta_description='발목 살 빼는 법, 부종·지방·근육 유형 구분을 정리했어요.',
    )
    assert html.startswith("<title>발목 살 빼는 법 | 제로클리닉</title>\n")
    assert '<meta name="description" content="발목 살 빼는 법, 부종·지방·근육 유형 구분을 정리했어요.">' in html  # noqa: E501
    assert f'<h1 style="{H1_STYLE}">신사다이어트 발목 살 빼는 법｜종아리·발목 라인 관리 가이드</h1>' in html
    assert html.rstrip().endswith("<p>첫 문단</p>")


def test_meta_title_falls_back_to_the_title():
    html = render([], title="제목만", meta_description="")
    assert "<title>제목만</title>" in html


def test_headings_carry_inline_margins_not_br():
    """팀 스레드 10번 — 간격은 코드 보기에서 margin 으로 줘야 h 태그가 안 씹힙니다."""
    html = render_blocks([h2("발목이 굵어 보이는 이유"), para("본문"), h3("Q1. 질문")])
    assert f'<h2 style="{H2_STYLE}">발목이 굵어 보이는 이유</h2>' in html
    assert f'<h3 style="{H3_STYLE}">Q1. 질문</h3>' in html
    assert "<br>" not in html.split("</h2>")[0]


def test_h1_in_body_is_lowered_to_h2():
    html = render_blocks([block("heading_1", rt("본문 속 H1"))])
    assert "<h2 " in html and "<h1" not in html


def test_lists_become_paragraph_lines():
    """팀 스레드 8번 — <ul>/<ol> 은 사이트 템플릿에서 서식이 깨져 <p> 로 풉니다."""
    html = render_blocks(
        [
            bullet(rt("첫째")),
            bullet(rt("둘째"), children=[bullet(rt("하위"))]),
            block("numbered_list_item", rt("하나")),
            block("numbered_list_item", rt("둘")),
        ]
    )
    assert "<ul" not in html and "<ol" not in html and "<li" not in html
    assert "<p>• 첫째</p>" in html
    assert "<p>&nbsp;&nbsp;&nbsp;&nbsp;- 하위</p>" in html
    assert "<p>1. 하나</p>" in html and "<p>2. 둘</p>" in html


def test_table_shape_matches_the_published_article():
    header = {"object": "block", "type": "table_row",
              "table_row": {"cells": [[rt("유형")], [rt("특성")]]}}
    row = {"object": "block", "type": "table_row",
           "table_row": {"cells": [[rt("부종형", bold=True)], [rt("림프 순환 저하")]]}}
    table = {
        "object": "block",
        "type": "table",
        "table": {"has_column_header": True},
        "_children": [header, row],
    }
    html = render_blocks([table])
    assert html.startswith("<table>\n<thead>\n<tr>\n<th>유형</th>\n<th>특성</th>\n</tr>\n</thead>")
    body = (
        "<tbody>\n<tr>\n<td><strong>부종형</strong></td>\n<td>림프 순환 저하</td>\n</tr>\n"
        "</tbody>\n</table>"
    )
    assert body in html
    assert "style=" not in html  # 표는 사이트 CSS 에 맡깁니다.


def test_uploaded_image_is_wrapped_like_the_team_did():
    img = image_block(url="/files/editor/2026.jpg", media_id=0, alt="발목 살 빼는 법")
    html = render_blocks([para("앞"), img])
    assert '<p><br></p><div><img src="/files/editor/2026.jpg" alt="발목 살 빼는 법"></div>' in html
    assert "wp:image" not in html and "<figure" not in html


def test_notion_hosted_images_are_dropped():
    """노션 첨부 주소는 1시간 뒤 만료됩니다. 본문에 그대로 두면 깨진 그림이 됩니다."""
    html = render_blocks([{"object": "block", "type": "image", "image": {"file": {"url": "https://s3/x"}}}])
    assert html == ""


def test_markup_in_text_is_escaped():
    html = render_blocks([para("<script>alert(1)</script>")])
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_empty_paragraphs_are_dropped():
    assert render_blocks([para(""), para("있음"), para("")]) == "<p>있음</p>"


def test_callout_keeps_its_emoji():
    callout = {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": [rt("체성분 검사 평가")], "icon": {"emoji": "✅"}},
    }
    assert render_blocks([callout]) == "<p>✅ 체성분 검사 평가</p>"


# ------------------------------------------------- 게시판 DB가 담지 못하는 네 바이트 문자


def test_four_byte_emoji_never_reach_the_board():
    """게시판 DB가 세 바이트 utf8 이라 네 바이트 문자를 담지 못합니다.

    넣으면 '?' 로 바뀌거나 사라집니다. 실제로 올라간 글 36편에 네 바이트
    문자는 하나도 살아남지 못했고, 원고의 📚 가 그렇게 날아갔습니다.
    """
    html = render_blocks([para("📚 함께 읽으면 좋은 글: 지방분해주사 성분 비교")])

    assert "📚" not in html
    assert max(ord(c) for c in html) <= 0xFFFF
    # 자리만 비우지 않고 쓸모 있는 기호로 바꿉니다.
    assert html == "<p>▪ 함께 읽으면 좋은 글: 지방분해주사 성분 비교</p>"


def test_three_byte_emoji_are_left_alone():
    """✅ ➡ ▪ 는 게시판에서 멀쩡히 살아남습니다. 건드리면 손해입니다."""
    html = render_blocks([para("✅ 성분명을 확인할 수 있는지"), para("➡️ 다음 단계")])

    assert "✅" in html
    assert "➡️" in html


def test_an_unmapped_four_byte_emoji_is_dropped_without_a_hole():
    """대응을 적어 두지 않은 이모지는 지웁니다. 빈자리에 겹공백이 남으면 안 됩니다."""
    html = render_blocks([para("🎉 축하합니다")])

    assert html == "<p>축하합니다</p>"


def test_the_whole_document_is_cleaned_not_just_the_body():
    """제목·메타에 섞여 들어가도 똑같이 걸러야 합니다."""
    html = render([para("본문")], title="📚 가이드", meta_description="📌 요약")

    assert max(ord(c) for c in html) <= 0xFFFF
