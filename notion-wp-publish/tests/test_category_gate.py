"""분류 이름이 워드프레스에 없으면 발행을 멈춥니다.

예전에는 없는 이름이면 그 이름으로 분류를 새로 만들었습니다. 오타가 나도 발행은
성공으로 보고돼서, 유령 분류에 글 하나가 격리된 걸 며칠 뒤에나 발견하게 됩니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.publish import Publisher
from notionwp.wordpress import WordPressClient, WordPressError
from test_gate_schema import CONFIG, complete_page
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: F401


class FakeSession:
    """카테고리 목록만 돌려주는 최소 세션."""

    def __init__(self, categories):
        self.headers = {}
        self._categories = categories
        self.created: list[str] = []

    def request(self, method, url, **kwargs):
        if method == "POST":  # 분류 생성은 더 이상 일어나면 안 됩니다.
            self.created.append(url)
        return FakeResponse(self._categories)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.ok = True
        self.headers: dict = {}
        self.text = ""
        self.content = b"[]"

    def json(self):
        return self._payload


def client(categories):
    return WordPressClient(CONFIG.wordpress, "user", "pw", session=FakeSession(categories))


# ------------------------------------------------------------------ 이름 대조


def test_existing_name_resolves_to_its_id():
    wp = client([{"id": 12, "name": "색소 이야기"}, {"id": 13, "name": "피부질환"}])
    assert wp.resolve_category("색소 이야기") == 12


def test_html_escaped_names_still_match():
    wp = client([{"id": 5, "name": "리프팅 &amp; 탄력"}])
    assert wp.resolve_category("리프팅 & 탄력") == 5


def test_missing_name_raises_and_lists_what_exists():
    wp = client([{"id": 12, "name": "색소 이야기"}])

    with pytest.raises(WordPressError) as err:
        wp.resolve_category("색소이야기")  # 띄어쓰기 하나 차이

    assert "색소이야기" in str(err.value)
    assert "색소 이야기" in str(err.value)  # 고칠 수 있게 실제 목록을 보여줍니다


def test_nothing_is_created_on_a_miss():
    session = FakeSession([{"id": 12, "name": "색소 이야기"}])
    wp = WordPressClient(CONFIG.wordpress, "user", "pw", session=session)

    with pytest.raises(WordPressError):
        wp.resolve_category("없는 분류")

    assert session.created == []


def test_empty_category_publishes_without_one():
    wp = client([{"id": 12, "name": "색소 이야기"}])
    assert wp.resolve_category("") is None


# ------------------------------------------------------------------ 발행 흐름


def test_publish_stops_before_going_public():
    """분류가 어긋나면 공개되지 않고 '발행 오류'로 넘어갑니다."""
    wp = FakeWordPress(fail_on="resolve_category")
    notion = FakeNotion([complete_page()], sample_page())

    outcomes = Publisher(CONFIG, notion=notion, wp=wp).run()

    assert not outcomes[0].published
    assert outcomes[0].error
    assert "publish" not in [p.get("status") for p in wp.posts.values()]
    # 노션에는 '발행 오류'만 기록되고 URL 은 쓰이지 않습니다.
    written = [props for _, props in notion.updates]
    assert any("진행 상황" in p for p in written)
    assert not any("URL" in p for p in written)


# ------------------------------------------------------------------ FAQ 경고


def block(kind: str, text: str) -> dict:
    key = kind
    return {"type": kind, key: {"rich_text": [{"plain_text": text, "annotations": {}}]}}


def body_blocks(*, with_questions: bool) -> list[dict]:
    blocks = [
        block("heading_2", "클리어톤의원은 어떤 병원인가요?"),
        block("paragraph", "소개 문단입니다."),
        block("heading_2", "[FAQ] 자주 묻는 질문"),
    ]
    if with_questions:
        blocks += [block("heading_3", "Q1. 예약은 어떻게 하나요?"), block("paragraph", "전화로 가능합니다.")]
    else:
        # 질문이 헤딩이 아니라 문단으로만 적힌 원고. FAQ 스키마를 만들 수 없습니다.
        blocks += [block("paragraph", "Q1. 예약은 어떻게 하나요? 전화로 가능합니다.")]
    return blocks


def publish_with(blocks):
    wp = FakeWordPress()
    notion = FakeNotion([complete_page()], blocks)
    return Publisher(CONFIG, notion=notion, wp=wp).run()[0]


def test_faq_section_without_extractable_questions_warns():
    out = publish_with(body_blocks(with_questions=False))

    assert out.published  # 막지는 않습니다. BlogPosting 은 정상입니다
    assert out.warnings
    assert "FAQ" in out.warnings[0]


def test_well_formed_faq_produces_no_warning():
    out = publish_with(body_blocks(with_questions=True))

    assert out.published
    assert out.warnings == []


def test_article_without_any_faq_section_is_not_warned():
    blocks = [block("heading_2", "본문"), block("paragraph", "FAQ 가 없는 글입니다.")]
    out = publish_with(blocks)

    assert out.published
    assert out.warnings == []
