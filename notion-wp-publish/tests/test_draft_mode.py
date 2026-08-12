"""--draft (임시저장) 모드 검증.

핵심: 워드프레스에 초안과 Rank Math 까지 다 만들되
공개하지 않고 노션은 일절 건드리지 않아야 합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.config import Config
from notionwp.publish import Publisher, summarize
from notionwp.wordpress import WordPressError
from test_gate_schema import CONFIG, complete_page
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: F401


def build_draft(wp, pages=None):
    notion = FakeNotion(pages or [complete_page()], sample_page())
    return Publisher(CONFIG, draft=True, notion=notion, wp=wp), notion


def test_post_stays_draft():
    wp = FakeWordPress()
    pub, _ = build_draft(wp)

    outcomes = pub.run()

    assert outcomes[0].drafted
    assert not outcomes[0].published
    post_id = next(iter(wp.posts))
    assert wp.posts[post_id]["status"] == "draft"
    # 공개로 바꾸는 호출이 아예 없어야 합니다.
    assert all(f.get("status") != "publish" for f in [wp.posts[post_id]])


def test_notion_is_untouched():
    wp = FakeWordPress()
    pub, notion = build_draft(wp)

    pub.run()

    assert notion.updates == [], "임시저장 모드는 노션을 건드리면 안 됩니다"


def test_images_and_rank_math_still_applied():
    """임시저장이라도 실제 발행 경로를 다 태워봐야 테스트 의미가 있습니다."""
    wp = FakeWordPress()
    pub, _ = build_draft(wp)

    pub.run()

    assert len(wp.media) == 3  # 썸네일 1 + 본문 2
    payload = wp.seo[next(iter(wp.posts))]
    assert payload["rank_math_title"]
    assert payload["rank_math_description"]
    assert [s["@type"] for s in payload["schemas"]] == ["BlogPosting", "FAQPage"]

    post = wp.posts[next(iter(wp.posts))]
    assert post["featured_media"] == wp.media[0]["id"]
    assert post["content"].count("<!-- wp:image") == 2


def test_edit_link_is_reported():
    wp = FakeWordPress()
    pub, _ = build_draft(wp)

    outcomes = pub.run()
    post_id = next(iter(wp.posts))

    assert outcomes[0].edit_link == (
        f"https://cleartone.co.kr/wp-admin/post.php?post={post_id}&action=edit"
    )


def test_failure_does_not_mark_notion_error_in_draft_mode():
    wp = FakeWordPress(fail_on="apply_seo")
    pub, notion = build_draft(wp)

    outcomes = pub.run()

    assert outcomes[0].error
    assert notion.updates == []


def test_rerunning_draft_reuses_the_same_post():
    wp = FakeWordPress(existing={"found": True, "post_id": 55, "status": "draft", "link": ""})
    wp.posts[55] = {"status": "draft"}  # 워드프레스에 이미 남아 있는 초안
    pub, _ = build_draft(wp)

    outcomes = pub.run()

    assert outcomes[0].drafted
    assert "create_post" not in wp.calls  # 새로 만들지 않고 기존 초안을 덮어씁니다
    assert wp.posts[55]["status"] == "draft"  # 공개로 넘어가면 안 됩니다


def test_already_published_still_skipped_in_draft_mode():
    wp = FakeWordPress(
        existing={"found": True, "post_id": 55, "status": "publish", "link": "https://x/"}
    )
    pub, _ = build_draft(wp)

    outcomes = pub.run()

    assert outcomes[0].skipped
    assert not outcomes[0].drafted


def test_summary_mentions_draft_and_how_to_publish():
    wp = FakeWordPress()
    pub, _ = build_draft(wp)

    text = summarize(pub.run())

    assert "임시저장 1건" in text
    assert "공개되지 않았고" in text
    assert "--draft 없이 다시 돌리면" in text


def test_dry_run_and_draft_are_mutually_exclusive():
    from notionwp.__main__ import main

    cfg_path = str(Path(__file__).resolve().parents[1] / "config" / "cleartone.json")
    assert main(["--config", cfg_path, "--dry-run", "--draft"]) == 2


def test_config_still_loads():
    assert Config.load(
        Path(__file__).resolve().parents[1] / "config" / "cleartone.json"
    ).client == "클리어톤의원"


def test_wordpress_error_is_importable():
    assert issubclass(WordPressError, RuntimeError)
