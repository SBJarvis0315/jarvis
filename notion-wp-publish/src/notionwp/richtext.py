"""노션 rich_text 배열을 다루는 헬퍼.

노션 API의 텍스트는 어디서나 `rich_text: [...]` 형태로 내려옵니다.
평문이 필요한 곳(제목 비교, 섹션 판별)과 HTML이 필요한 곳(본문 변환)이
섞여 있어 두 가지 변환을 한곳에 모아둡니다.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any

# 노션이 마크다운 특수문자를 이스케이프해서 돌려주는 경우가 있습니다.
# 실제 사례: 제목 속성의 "기미 레이저 횟수 \| 클리어톤의원"
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>])")

# 헤딩 앞에 붙은 이모지·기호를 걷어내기 위한 패턴.
_LEADING_SYMBOLS = re.compile(
    r"^[\s -⁯←-⯿⸀-⹿"
    r"\U0001f000-\U0001faff︀-️‍]+"
)


def unescape(text: str) -> str:
    """노션이 붙여 보낸 백슬래시 이스케이프를 제거합니다."""
    return _ESCAPED.sub(r"\1", text or "")


def plain_text(rich_text: Iterable[dict[str, Any]] | None) -> str:
    """rich_text 배열 → 평문."""
    if not rich_text:
        return ""
    return unescape("".join(node.get("plain_text", "") for node in rich_text))


def strip_markers(text: str) -> str:
    """앞머리 이모지/기호와 볼드 표시를 걷어낸 뒤 공백을 정리합니다.

    "## 📋 작성 메타 정보" 같은 헤딩을 "작성 메타 정보"로 만들어
    섹션 판별을 안정적으로 하기 위한 용도입니다.
    """
    text = unescape(text or "").strip()
    text = re.sub(r"^\*+|\*+$", "", text).strip()
    text = _LEADING_SYMBOLS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def to_html(rich_text: Iterable[dict[str, Any]] | None) -> str:
    """rich_text 배열 → 인라인 HTML.

    구텐베르크 블록 안에 그대로 넣을 수 있는 형태로 만듭니다.
    볼드/이탤릭/취소선/코드/링크만 다룹니다 — 원고에서 실제로 쓰이는 범위입니다.
    """
    if not rich_text:
        return ""

    out: list[str] = []
    for node in rich_text:
        text = unescape(node.get("plain_text", ""))
        if not text:
            continue

        # 노션 rich_text의 개행은 구텐베르크에서 <br>로 살립니다.
        fragment = html.escape(text, quote=False).replace("\n", "<br>")

        ann = node.get("annotations") or {}
        if ann.get("code"):
            fragment = f"<code>{fragment}</code>"
        if ann.get("bold"):
            fragment = f"<strong>{fragment}</strong>"
        if ann.get("italic"):
            fragment = f"<em>{fragment}</em>"
        if ann.get("strikethrough"):
            fragment = f"<s>{fragment}</s>"
        if ann.get("underline"):
            fragment = f"<u>{fragment}</u>"

        href = node.get("href")
        if href:
            fragment = f'<a href="{html.escape(href, quote=True)}">{fragment}</a>'

        out.append(fragment)

    return "".join(out)


def block_text(block: dict[str, Any]) -> str:
    """블록 종류와 무관하게 그 블록의 평문을 꺼냅니다."""
    payload = block.get(block.get("type", ""), {})
    if isinstance(payload, dict):
        return plain_text(payload.get("rich_text"))
    return ""
