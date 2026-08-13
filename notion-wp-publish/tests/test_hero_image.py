"""숏폼 히어로 이미지 — 썸네일 한 장을 대표 이미지 + 본문 최상단에 함께 씁니다.

롱폼·엔티티는 영향을 받지 않아야 합니다. 같은 파일이 워드프레스에 두 번
올라가지 않는 것도 이 동작의 핵심입니다.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.publish import Publisher, check_properties, uses_hero_image
from test_gate_schema import CONFIG, complete_page
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: F401

TODAY = date(2026, 8, 12)

HERO = replace(CONFIG, render=replace(CONFIG.render, hero_image_types=["숏폼"]))
PLAIN = replace(CONFIG, render=replace(CONFIG.render, hero_image_types=[]))


def page_of_type(kind: str, *, body_images: bool) -> dict:
    page = complete_page()
    page["properties"]["유형"] = {"select": {"name": kind}}
    if not body_images:
        page["properties"]["본문 이미지"] = {"files": []}
    return page


# ------------------------------------------------------------------ 유형 판별


def test_only_listed_types_use_hero():
    assert uses_hero_image(HERO, page_of_type("숏폼", body_images=True)["properties"])
    assert not uses_hero_image(HERO, page_of_type("롱폼", body_images=True)["properties"])
    assert not uses_hero_image(HERO, page_of_type("엔티티", body_images=True)["properties"])


def test_disabled_when_not_configured():
    # hero_image_types 가 비어 있으면 어떤 유형도 해당하지 않습니다.
    assert not uses_hero_image(PLAIN, page_of_type("숏폼", body_images=True)["properties"])


# ------------------------------------------------------------------ 발행 게이트


def test_shortform_publishes_without_body_images():
    cand = check_properties(HERO, page_of_type("숏폼", body_images=False), on=TODAY)
    assert cand.ok, cand.reasons


def test_longform_still_requires_body_images():
    cand = check_properties(HERO, page_of_type("롱폼", body_images=False), on=TODAY)
    assert "본문 이미지가 비어 있음" in cand.reasons


def test_shortform_still_requires_thumbnail():
    page = page_of_type("숏폼", body_images=False)
    page["properties"]["썸네일"] = {"files": []}
    cand = check_properties(HERO, page, on=TODAY)
    assert "썸네일이 비어 있음" in cand.reasons


# ------------------------------------------------------------------ 발행 결과


def _publish(cfg, page):
    wp = FakeWordPress()
    Publisher(cfg, notion=FakeNotion([page], sample_page()), wp=wp).run()
    return wp


def _only_post(wp) -> dict:
    assert len(wp.posts) == 1
    return next(iter(wp.posts.values()))


def test_thumbnail_appears_once_in_media_and_once_at_top():
    wp = _publish(HERO, page_of_type("숏폼", body_images=False))

    # 미디어 업로드는 단 한 번 — 대표 이미지와 본문이 같은 파일을 공유합니다.
    assert len(wp.media) == 1
    thumb = wp.media[0]

    post = _only_post(wp)
    assert post["featured_media"] == thumb["id"]

    content = post["content"]
    # 본문 첫 블록이 그 이미지여야 합니다.
    assert content.lstrip().startswith("<!-- wp:image")
    # 같은 미디어 ID를 재사용하므로 본문에 딱 한 번만 등장합니다.
    assert content.count(f'"id":{thumb["id"]}') == 1


def test_longform_body_images_are_unaffected():
    wp = _publish(HERO, page_of_type("롱폼", body_images=True))
    post = _only_post(wp)
    # 썸네일은 대표 이미지로만 쓰이고 본문에는 재사용되지 않습니다.
    assert len(wp.media) > 1
    thumb_id = post["featured_media"]
    assert f'"id":{thumb_id}' not in post["content"]
