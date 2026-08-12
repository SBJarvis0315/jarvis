from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.extract import extract
from notionwp.gutenberg import RenderOptions, image_block, render
from notionwp.images import plan_placements, target_filename


def rendered() -> str:
    return render(extract(sample_page()).body)


# --------------------------------------------------------------- 구텐베르크 변환


def test_headings_use_gutenberg_markup():
    out = rendered()
    assert '<!-- wp:heading -->\n<h2 class="wp-block-heading">' in out
    assert '<!-- wp:heading {"level":3} -->' in out


def test_spacer_inserted_before_headings_but_not_the_first():
    out = rendered()
    assert '<!-- wp:spacer {"height":"20px"} -->' in out
    # 첫 헤딩 앞에는 공백이 붙지 않아야 합니다.
    assert not out.lstrip().startswith("<!-- wp:spacer")


def test_spacer_can_be_disabled():
    out = render(extract(sample_page()).body, RenderOptions(spacer_before_headings=False))
    assert "wp:spacer" not in out


def test_lists_are_grouped_into_one_block():
    out = rendered()
    assert out.count("<!-- wp:list -->") + out.count('<!-- wp:list {"ordered":true} -->') >= 2
    assert "<!-- wp:list-item -->" in out


def test_todo_items_become_plain_bullets():
    out = rendered()
    assert "감별 과정을 거치는지" in out
    # 체크박스 마크업이 새어나가면 안 됩니다.
    assert "type=\"checkbox\"" not in out


def test_table_renders_with_header_and_center_alignment():
    out = rendered()
    assert "<!-- wp:table -->" in out
    assert "<thead>" in out and "<th style=\"text-align:center\">" in out
    assert "색소 병변" in out


def test_links_and_bold_are_preserved():
    out = rendered()
    assert '<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC12696807/">' in out
    assert "<strong>" in out


def test_html_is_escaped():
    from fixtures import para

    out = render([para("<script>alert(1)</script>")])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_image_block_markup():
    out = render([image_block(url="https://x.test/a.jpg", media_id=42, alt="검사 장면")])
    assert '<!-- wp:image {"id":42,"sizeSlug":"large","linkDestination":"none"} -->' in out
    assert 'alt="검사 장면"' in out
    assert 'class="wp-image-42"' in out


# --------------------------------------------------------------------- 이미지 배치


def test_placements_follow_the_alt_guide_order():
    ex = extract(sample_page())
    placements = plan_placements(ex.body, ex.image_hints, image_count=4)

    assert len(placements) == 4
    # 도입부 이미지는 본문 맨 앞.
    assert placements[0].index == 0
    assert placements[0].alt == "기미 레이저 치료 회차를 상담하는 진료 장면"
    # 위치는 문서 순서대로 단조 증가해야 합니다.
    assert [p.index for p in placements] == sorted(p.index for p in placements)
    # 클로징 ALT가 마지막에 붙습니다.
    assert placements[-1].alt == "클리어톤의원 색소 레이저 장비"


def test_table_hint_lands_in_the_section_that_has_the_table():
    ex = extract(sample_page())
    placements = plan_placements(ex.body, ex.image_hints, image_count=4)

    table_idx = next(i for i, b in enumerate(ex.body) if b.get("type") == "table")
    comparison = next(p for p in placements if p.alt.startswith("기미 흑자 검버섯"))
    # 표를 품은 구간 안에 들어가야 합니다 (표보다 앞, 도입부보다 뒤).
    assert 0 < comparison.index <= table_idx


def test_extra_images_beyond_guide_get_derived_alt():
    ex = extract(sample_page())
    placements = plan_placements(ex.body, ex.image_hints, image_count=5)

    assert len(placements) == 5
    assert all(p.alt for p in placements), "ALT가 빈 이미지가 있으면 안 됩니다"


def test_placement_without_hints_spreads_evenly():
    ex = extract(sample_page())
    placements = plan_placements(ex.body, [], image_count=3)

    assert len(placements) == 3
    assert len({p.index for p in placements}) == 3
    assert all(p.alt for p in placements)


def test_placements_can_be_applied_in_order():
    ex = extract(sample_page())
    placements = plan_placements(ex.body, ex.image_hints, image_count=4)

    body = list(ex.body)
    for offset, p in enumerate(placements):
        body.insert(p.index + offset, image_block(url="u", media_id=1, alt=p.alt))

    out = render(body)
    assert out.count("<!-- wp:image") == 4


# ------------------------------------------------------------------- 파일명 생성


def test_filenames_are_slug_based_ascii():
    assert (
        target_filename("melasma-laser-sessions", 1, "https://s3/기미레이저횟수1.jpg")
        == "melasma-laser-sessions-1.jpg"
    )
    assert (
        target_filename("melasma-laser-sessions", None, "https://s3/썸네일.png?X-Amz=1")
        == "melasma-laser-sessions-thumbnail.png"
    )
