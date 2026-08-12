"""prepare → (ALT 채우기) → publish 3단계 흐름 검증."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.extract import extract
from notionwp.images import spread_evenly
from notionwp.plan import PagePlan, outline
from notionwp.publish import Publisher, summarize
from test_gate_schema import CONFIG, complete_page
from test_publish_flow import BASE, FakeNotion, FakeWordPress, _no_network  # noqa: F401


def build(wp, *, plan_root=None, draft=False):
    notion = FakeNotion([complete_page()], sample_page())
    return Publisher(CONFIG, draft=draft, plan_root=plan_root, notion=notion, wp=wp), notion


# ------------------------------------------------------------------- 균등 배치


def test_spread_evenly_distributes_across_sections():
    body = extract(sample_page()).body
    positions = spread_evenly(body, 4)

    assert len(positions) == 4
    assert positions == sorted(positions)
    assert len(set(positions)) == 4, "같은 자리에 몰리면 안 됩니다"


def test_spread_evenly_handles_more_images_than_sections():
    body = extract(sample_page()).body
    positions = spread_evenly(body, 40)
    assert len(positions) == 40


def test_spread_evenly_with_no_images():
    assert spread_evenly(extract(sample_page()).body, 0) == []


# --------------------------------------------------------------------- 개요


def test_outline_starts_with_intro_and_lists_headings():
    body = extract(sample_page()).body
    sections = outline(body)

    assert sections[0].heading == "(도입부)"
    assert sections[0].anchor == 0
    headings = [s.heading for s in sections]
    assert "기미 레이저 횟수, 먼저 알아둘 핵심 포인트 7가지" in headings
    # 각 구간에 본문 발췌가 붙어 ALT를 글 내용에 맞출 수 있어야 합니다.
    assert any(s.excerpt for s in sections[1:])


# --------------------------------------------------------------------- prepare


def test_prepare_downloads_images_and_writes_plan(tmp_path):
    wp = FakeWordPress()
    pub, notion = build(wp)

    outcomes = pub.prepare(tmp_path)

    assert outcomes[0].prepared
    assert not outcomes[0].published
    # 준비 단계는 워드프레스를 전혀 건드리지 않습니다.
    assert wp.calls == []
    assert notion.updates == []

    directory = next(tmp_path.iterdir())
    plan = PagePlan.load(directory)

    assert plan.slug == "melasma-laser-sessions"
    assert len(plan.images) == 2
    assert plan.thumbnail
    assert (directory / plan.thumbnail).exists()
    for img in plan.images:
        assert (directory / img.original).exists()
        assert img.alt == "", "ALT는 사람이 채우도록 비워둬야 합니다"


def test_prepare_summary_tells_you_what_to_do_next(tmp_path):
    pub, _ = build(FakeWordPress())
    text = summarize(pub.prepare(tmp_path))

    assert "준비 1건" in text
    assert "alt" in text.lower()
    assert "아직 아무것도 발행하지 않았습니다" in text


# ---------------------------------------------------------------- plan 기반 발행


def fill_alts(root: Path, alts: list[str]) -> Path:
    directory = next(root.iterdir())
    plan = PagePlan.load(directory)
    for img, alt in zip(plan.images, alts, strict=True):
        img.alt = alt
    plan.thumbnail_alt = "대표 이미지 설명"
    plan.save(directory)
    return directory


def test_publish_uses_plan_alts_and_anchors(tmp_path):
    pub, _ = build(FakeWordPress())
    pub.prepare(tmp_path)
    fill_alts(tmp_path, ["레이저 장비를 살펴보는 진료 장면", "상담실에서 경과를 설명하는 모습"])

    wp = FakeWordPress()
    pub2, _ = build(wp, plan_root=tmp_path, draft=True)
    outcomes = pub2.run()

    assert outcomes[0].drafted
    alts = [m["alt"] for m in wp.media]
    assert alts[0] == "대표 이미지 설명"
    assert alts[1:] == [
        "레이저 장비를 살펴보는 진료 장면",
        "상담실에서 경과를 설명하는 모습",
    ]

    content = wp.posts[next(iter(wp.posts))]["content"]
    assert "레이저 장비를 살펴보는 진료 장면" in content
    # 원고의 ALT 가이드 문구는 더 이상 쓰이지 않아야 합니다.
    assert "기미 레이저 치료 회차를 상담하는 진료 장면" not in content


def test_publish_refuses_when_alt_is_still_empty(tmp_path):
    pub, _ = build(FakeWordPress())
    pub.prepare(tmp_path)

    wp = FakeWordPress()
    pub2, _ = build(wp, plan_root=tmp_path, draft=True)
    outcomes = pub2.run()

    assert outcomes[0].error
    assert "ALT가 비어" in outcomes[0].error
    assert "create_post" not in wp.calls


def test_plan_anchor_edits_are_respected(tmp_path):
    pub, _ = build(FakeWordPress())
    pub.prepare(tmp_path)

    directory = fill_alts(tmp_path, ["첫 번째", "두 번째"])
    plan = PagePlan.load(directory)
    plan.images[0].anchor = 0  # 도입부로 옮김
    plan.images[1].anchor = 1
    plan.save(directory)

    wp = FakeWordPress()
    pub2, _ = build(wp, plan_root=tmp_path, draft=True)
    pub2.run()

    content = wp.posts[next(iter(wp.posts))]["content"]
    assert content.lstrip().startswith("<!-- wp:image")


def test_falls_back_to_guide_when_plan_missing(tmp_path):
    """plan 폴더를 가리켰지만 해당 원고의 plan.json 이 없으면 예전 방식으로 갑니다."""
    wp = FakeWordPress()
    pub, _ = build(wp, plan_root=tmp_path / "empty", draft=True)

    outcomes = pub.run()

    assert outcomes[0].drafted
    alts = [m["alt"] for m in wp.media[1:]]
    assert alts[0] == "기미 레이저 치료 회차를 상담하는 진료 장면"


def test_images_are_not_refetched_from_notion_when_plan_exists(tmp_path, monkeypatch):
    """prepare 때 받아둔 파일을 쓰므로 노션 주소 만료와 무관해야 합니다."""
    pub, _ = build(FakeWordPress())
    pub.prepare(tmp_path)
    fill_alts(tmp_path, ["가", "나"])

    import notionwp.publish as publish_mod

    def explode(url, session=None):
        raise AssertionError("plan 이 있으면 노션에서 다시 내려받으면 안 됩니다")

    monkeypatch.setattr(publish_mod, "download", explode)

    wp = FakeWordPress()
    pub2, _ = build(wp, plan_root=tmp_path, draft=True)
    outcomes = pub2.run()

    assert outcomes[0].drafted
    assert len(wp.media) == 3
