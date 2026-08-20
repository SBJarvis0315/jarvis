"""Rank Math 스키마 생성.

내부 가이드 기준을 그대로 따릅니다.
  - 기본으로 붙는 Article 스키마는 쓰지 않습니다 (mu-plugin 이 기존 스키마를 먼저 비웁니다).
  - 정보성 롱폼은 BlogPosting + FAQPage 두 가지만 씁니다.
  - FAQPage 는 원고에 FAQ 섹션이 실제로 있을 때만 붙입니다.
"""

from __future__ import annotations

import re
from typing import Any

from .richtext import block_text, strip_markers

Block = dict[str, Any]

FAQ_HEADING_HINTS = ("faq", "자주 묻는 질문", "자주묻는질문")

#: "Q1.", "Q 1)", "1." 처럼 붙는 질문 번호를 떼어냅니다.
_Q_PREFIX = re.compile(r"^\s*(?:Q\s*\.?\s*\d*|질문\s*\d*)\s*[.):]?\s*", re.IGNORECASE)


def _heading_level(block: Block) -> int:
    """heading_2 → 2. 헤딩이 아니면 0."""
    btype = str(block.get("type") or "")
    return int(btype[-1]) if btype.startswith("heading_") and btype[-1].isdigit() else 0


def has_faq_heading(body: list[Block]) -> bool:
    """원고에 FAQ 섹션이 있는지만 봅니다.

    문답을 못 뽑았을 때, 원고에 FAQ 가 아예 없어서인지 형식이 어긋나서인지를
    구분하는 데 씁니다.
    """
    for block in body:
        if not _heading_level(block):
            continue
        text = strip_markers(block_text(block)).lower()
        if any(hint in text for hint in FAQ_HEADING_HINTS):
            return True
    return False


def extract_faqs(body: list[Block]) -> list[dict[str, str]]:
    """본문에서 FAQ 문답을 뽑아냅니다.

    헤딩 깊이를 고정하지 않습니다. 자동 생성 원고는 `## [FAQ] …` 아래 `### Q1.` 이지만,
    사람이 쓴 원고는 글 전체가 H2 하나 아래 묶여 있어 `### [FAQ] …` + `#### Q1.` 이
    되기도 합니다. 깊이를 h2/h3 으로 못 박아두면 후자에서 FAQ 스키마가 통째로 빠집니다.

    FAQ 헤딩을 찾은 뒤, 그 아래에서 처음 나오는 더 깊은 헤딩을 질문 단계로 삼고,
    FAQ 헤딩과 같거나 더 얕은 헤딩이 나오면 섹션이 끝난 것으로 봅니다.
    """
    start = None
    section_level = 0

    for i, block in enumerate(body):
        level = _heading_level(block)
        if not level:
            continue
        text = strip_markers(block_text(block)).lower()
        if any(hint in text for hint in FAQ_HEADING_HINTS):
            start = i + 1
            section_level = level
            break

    if start is None:
        return []

    # 질문 단계는 FAQ 헤딩 아래에서 처음 만나는 더 깊은 헤딩으로 정합니다.
    question_level = 0
    for block in body[start:]:
        level = _heading_level(block)
        if not level:
            continue
        if level <= section_level:
            break
        question_level = level
        break

    if not question_level:
        return []

    faqs: list[dict[str, str]] = []
    question: str | None = None
    answer: list[str] = []

    def flush() -> None:
        if question and answer:
            faqs.append({"question": question, "answer": " ".join(answer).strip()})

    for block in body[start:]:
        level = _heading_level(block)

        if level and level <= section_level:
            break  # FAQ 섹션 종료

        if level == question_level:
            flush()
            question = _Q_PREFIX.sub("", strip_markers(block_text(block))).strip()
            answer = []
            continue

        if level:
            continue  # 답변 안의 더 깊은 소제목은 답변에 넣지 않습니다

        if question and block.get("type") in (
            "paragraph",
            "bulleted_list_item",
            "numbered_list_item",
        ):
            text = block_text(block).strip()
            if text:
                answer.append(text)

    flush()
    return [f for f in faqs if f["question"] and f["answer"]]


def build_schemas(
    *,
    body: list[Block],
    headline: str,
    description: str,
    permalink: str,
    published_iso: str,
    image_url: str = "",
    keywords: str = "",
    publisher_name: str = "",
    publisher_logo: str = "",
    author_name: str = "",
) -> list[dict[str, Any]]:
    """BlogPosting (+ FAQPage) 를 만들어 돌려줍니다."""
    blog_posting: dict[str, Any] = {
        "@type": "BlogPosting",
        # 구글이 권장하는 헤드라인 길이는 110자입니다.
        "headline": headline[:110],
        "description": description,
        "inLanguage": "ko-KR",
        "datePublished": published_iso,
        "dateModified": published_iso,
    }

    if permalink:
        blog_posting["mainEntityOfPage"] = {"@type": "WebPage", "@id": permalink}
        blog_posting["url"] = permalink
    if image_url:
        blog_posting["image"] = {"@type": "ImageObject", "url": image_url}
    if keywords:
        blog_posting["keywords"] = ", ".join(
            k.strip() for k in keywords.split(",") if k.strip()
        )
    if author_name:
        blog_posting["author"] = {"@type": "Organization", "name": author_name}
    if publisher_name:
        publisher: dict[str, Any] = {"@type": "Organization", "name": publisher_name}
        if publisher_logo:
            publisher["logo"] = {"@type": "ImageObject", "url": publisher_logo}
        blog_posting["publisher"] = publisher

    schemas: list[dict[str, Any]] = [blog_posting]

    faqs = extract_faqs(body)
    if faqs:
        schemas.append(
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": {"@type": "Answer", "text": faq["answer"]},
                    }
                    for faq in faqs
                ],
            }
        )

    return schemas
