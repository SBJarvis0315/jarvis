from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp.wordpress import Post
from test_publish_flow import FakeWordPress, _no_network, build  # noqa: F401


def test_schema_url_matches_the_real_permalink():
    """고유주소가 /카테고리/슬러그/ 형태여도 스키마 @id 가 실제 주소를 가리켜야 합니다."""
    wp = FakeWordPress()
    real = "https://cleartone.co.kr/color/melasma-laser-sessions/"

    original = wp.update_post

    def update(post_id, fields):
        result = original(post_id, fields)
        if fields.get("status") == "publish":
            return Post(id=post_id, link=real, status="publish")
        return result

    wp.update_post = update
    pub, _ = build(wp)

    outcomes = pub.run()

    assert outcomes[0].link == real

    payload = wp.seo[next(iter(wp.posts))]
    blog = next(s for s in payload["schemas"] if s["@type"] == "BlogPosting")
    assert blog["mainEntityOfPage"]["@id"] == real
    assert blog["url"] == real


def test_no_extra_seo_call_when_permalink_matches():
    wp = FakeWordPress()
    pub, _ = build(wp)
    pub.run()

    # 각인 1회 + 본 기입 1회. 주소가 예상과 같으면 보정 호출은 없어야 합니다.
    assert wp.calls.count("apply_seo") == 2
