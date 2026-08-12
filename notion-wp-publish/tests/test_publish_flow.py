"""오케스트레이터 종단 검증 — 네트워크 없이 가짜 클라이언트로 돌립니다.

특히 확인하려는 것:
  · 발행 순서가 '초안 → 노션 ID 각인 → SEO → 공개' 인가
  · 하루 두 번 돌아도 같은 원고가 두 번 나가지 않는가
  · 중간에 실패하면 공개되지 않고 '발행 오류'로 표시되는가
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import notionwp.publish as publish_mod
from fixtures import sample_page
from notionwp.publish import Publisher
from notionwp.wordpress import Media, Post, WordPressError
from test_gate_schema import CONFIG, complete_page


class FakeNotion:
    def __init__(self, pages, blocks):
        self.config = CONFIG.notion
        self._pages = pages
        self._blocks = blocks
        self.updates: list[tuple[str, dict]] = []

    def query_planner(self):
        return self._pages

    def fetch_blocks(self, page_id, depth=0):
        return self._blocks

    def update_page(self, page_id, properties):
        self.updates.append((page_id, properties))
        return {}


class FakeWordPress:
    def __init__(self, *, existing=None, fail_on: str = ""):
        self.calls: list[str] = []
        self.posts: dict[int, dict] = {}
        self.seo: dict[int, dict] = {}
        self.media: list[dict] = []
        self._existing = existing or {"found": False}
        self._fail_on = fail_on
        self._next_id = 100

    def _maybe_fail(self, name: str):
        self.calls.append(name)
        if self._fail_on == name:
            raise WordPressError(f"의도적 실패: {name}")

    def bridge_ping(self):
        self._maybe_fail("ping")
        return {"ok": True}

    def lookup_by_notion_id(self, notion_page_id):
        self._maybe_fail("lookup")
        return self._existing

    def upload_media(self, filename, data, alt=""):
        self._maybe_fail("upload_media")
        self._next_id += 1
        self.media.append({"filename": filename, "alt": alt, "id": self._next_id})
        return Media(id=self._next_id, url=f"https://cleartone.co.kr/uploads/{filename}")

    def slug_taken(self, slug):
        self._maybe_fail("slug_taken")
        return False

    def resolve_category(self, name):
        self._maybe_fail("resolve_category")
        return 7 if name else None

    def create_post(self, *, title, content, slug, status, categories=None, featured_media=None):
        self._maybe_fail("create_post")
        self._next_id += 1
        self.posts[self._next_id] = {
            "title": title,
            "content": content,
            "slug": slug,
            "status": status,
            "categories": categories,
            "featured_media": featured_media,
        }
        return Post(id=self._next_id, link="", status=status)

    def update_post(self, post_id, fields):
        self._maybe_fail("update_post")
        self.posts.setdefault(post_id, {}).update(fields)
        slug = self.posts[post_id].get("slug", "x")
        return Post(
            id=post_id,
            link=f"https://cleartone.co.kr/{slug}/",
            status=self.posts[post_id].get("status", "draft"),
        )

    def apply_seo(self, post_id, payload):
        self._maybe_fail("apply_seo")
        self.seo.setdefault(post_id, {}).update(payload)
        return {"ok": True}


def download_stub(url, session=None):
    return b"\x89PNG\r\n\x1a\n fake"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(publish_mod, "download", download_stub)
    monkeypatch.setattr(publish_mod, "today_kst", lambda: __import__("datetime").date(2026, 8, 12))


def build(wp, pages=None, blocks=None, dry_run=False):
    notion = FakeNotion(pages or [complete_page()], blocks or sample_page())
    return Publisher(CONFIG, dry_run=dry_run, notion=notion, wp=wp), notion


# ------------------------------------------------------------------ 정상 경로


def test_happy_path_publishes_and_writes_back():
    wp = FakeWordPress()
    pub, notion = build(wp)

    outcomes = pub.run()

    assert len(outcomes) == 1
    assert outcomes[0].published
    assert outcomes[0].link == "https://cleartone.co.kr/melasma-laser-sessions/"

    # 노션에 게재완료 + URL 이 기록되어야 합니다 (요구사항 3번).
    page_id, props = notion.updates[-1]
    assert props["진행 상황"]["status"]["name"] == "게재완료"
    assert props["URL"]["url"] == "https://cleartone.co.kr/melasma-laser-sessions/"


def test_publish_order_is_draft_then_stamp_then_seo_then_publish():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    order = [c for c in wp.calls if c in ("create_post", "apply_seo", "update_post")]
    assert order[0] == "create_post"
    assert order[1] == "apply_seo"  # 노션 ID 각인이 SEO 본문보다 먼저
    assert order[-1] == "update_post"  # 공개는 맨 마지막

    post_id = next(iter(wp.posts))
    assert wp.posts[post_id]["status"] == "publish"


def test_first_seo_call_stamps_notion_id():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    post_id = next(iter(wp.posts))
    assert wp.seo[post_id]["notion_page_id"] == "e2868fa2-06ff-8387-a4ce-018c082c51d5"


def test_rank_math_fields_and_schemas_are_sent():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    payload = wp.seo[next(iter(wp.posts))]
    assert payload["rank_math_title"] == "기미 레이저 횟수 | 클리어톤의원"
    assert payload["rank_math_description"].startswith("기미 레이저 횟수는")
    assert payload["rank_math_focus_keyword"].startswith("기미 레이저 횟수")
    assert [s["@type"] for s in payload["schemas"]] == ["BlogPosting", "FAQPage"]


def test_images_uploaded_with_slug_names_and_guide_alts():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    names = [m["filename"] for m in wp.media]
    assert names[0] == "melasma-laser-sessions-thumbnail.png"
    assert names[1:] == ["melasma-laser-sessions-1.jpg", "melasma-laser-sessions-2.jpg"]

    alts = [m["alt"] for m in wp.media[1:]]
    assert alts[0] == "기미 레이저 치료 회차를 상담하는 진료 장면"
    assert all(alts), "ALT 없는 이미지가 있으면 안 됩니다"


def test_thumbnail_is_set_as_featured_media():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    post = wp.posts[next(iter(wp.posts))]
    assert post["featured_media"] == wp.media[0]["id"]


def test_body_excludes_guide_and_review_sections():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    content = wp.posts[next(iter(wp.posts))]["content"]
    for banned in ("기획안입니다", "작성 메타 정보", "구조화 제안", "셀프 점검", "사용자 확인 요청"):
        assert banned not in content
    assert "핵심 포인트 7가지" in content
    assert content.count("<!-- wp:image") == 2


# ------------------------------------------------------------------ 중복 방지


def test_already_published_is_skipped():
    wp = FakeWordPress(
        existing={
            "found": True,
            "post_id": 55,
            "status": "publish",
            "link": "https://cleartone.co.kr/melasma-laser-sessions/",
        }
    )
    pub, notion = build(wp)

    outcomes = pub.run()

    assert outcomes[0].skipped
    assert not outcomes[0].published
    assert "create_post" not in wp.calls
    assert notion.updates == []


def test_leftover_draft_is_resumed_not_duplicated():
    wp = FakeWordPress(existing={"found": True, "post_id": 55, "status": "draft", "link": ""})
    pub, _ = build(wp)

    outcomes = pub.run()

    assert outcomes[0].published
    assert "create_post" not in wp.calls  # 새로 만들지 않고 기존 초안을 씁니다
    assert wp.posts[55]["status"] == "publish"


# --------------------------------------------------------------------- 실패 처리


def test_failure_before_publish_leaves_post_unpublished_and_marks_error():
    wp = FakeWordPress(fail_on="apply_seo")
    pub, notion = build(wp)

    outcomes = pub.run()

    assert not outcomes[0].published
    assert "의도적 실패" in outcomes[0].error

    post_id = next(iter(wp.posts))
    assert wp.posts[post_id]["status"] == "draft"  # 공개되지 않아야 합니다

    page_id, props = notion.updates[-1]
    assert props["진행 상황"]["status"]["name"] == "발행 오류"


def test_one_failure_does_not_block_other_rows():
    pages = [complete_page(), complete_page()]
    pages[1]["id"] = "another-page-id"

    wp = FakeWordPress()
    original_upload = wp.upload_media
    state = {"n": 0}

    def flaky(filename, data, alt=""):
        state["n"] += 1
        if state["n"] == 1:
            raise WordPressError("첫 번째 업로드 실패")
        return original_upload(filename, data, alt)

    wp.upload_media = flaky
    pub, _ = build(wp, pages=pages)

    outcomes = pub.run()

    assert len(outcomes) == 2
    assert outcomes[0].error
    assert outcomes[1].published


def test_dry_run_touches_nothing():
    wp = FakeWordPress()
    pub, notion = build(wp, dry_run=True)

    outcomes = pub.run()

    assert outcomes[0].skipped
    assert "create_post" not in wp.calls
    assert "upload_media" not in wp.calls
    assert notion.updates == []


def test_slug_collision_is_reported_not_silently_suffixed():
    wp = FakeWordPress()
    wp.slug_taken = lambda slug: True
    pub, _ = build(wp)

    outcomes = pub.run()

    assert not outcomes[0].published
    assert "슬러그" in outcomes[0].error
