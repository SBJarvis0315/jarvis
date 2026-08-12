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


def extract_faqs(body: list[Block]) -> list[dict[str, str]]:
    """본문에서 FAQ 문답을 뽑아냅니다.

    구조: `## [FAQ] …` 아래 `### Q1. 질문` + 뒤따르는 문단들이 답변.
    """
    start = None
    for i, block in enumerate(body):
        if block.get("type") != "heading_2":
            continue
        text = strip_markers(block_text(block)).lower()
        if any(hint in text for hint in FAQ_HEADING_HINTS):
            start = i + 1
            break

    if start is None:
        return []

    faqs: list[dict[str, str]] = []
    question: str | None = None
    answer: list[str] = []

    def flush() -> None:
        if question and answer:
            faqs.append({"question": question, "answer": " ".join(answer).strip()})

    for block in body[start:]:
        btype = block.get("type")

        if btype == "heading_2":
            break  # FAQ 섹션 종료

        if btype == "heading_3":
            flush()
            question = _Q_PREFIX.sub("", strip_markers(block_text(block))).strip()
            answer = []
            continue

        if question and btype in ("paragraph", "bulleted_list_item", "numbered_list_item"):
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
