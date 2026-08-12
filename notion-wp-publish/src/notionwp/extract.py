"""노션 원고 페이지에서 '발행할 본문'만 골라내는 모듈.

원고 페이지는 일정한 골격을 갖고 있습니다.

    [회색 callout]  콘텐츠 가이드 안내        ← 제외
    [토글] 콘텐츠 가이드                      ← 제외 (기획안)
    [🤖 callout] 자동 생성 원고 메타          ← 제외
    **메타 디스크립션** + 본문                ← 제외 (플래너 속성에 이미 있음)
    # H1 제목                                 ← 제외 (워드프레스 제목이 대신함)
    ## H2 ~ 클로징 CTA                        ← 본문
    ---
    ## 📋 작성 메타 정보                      ← 제외
    ## 🔧 구조화 제안                         ← 제외하되 ALT·스키마 지침으로 읽음
    ## ✅ 셀프 점검 결과                      ← 제외
    ## ⚠️ 사용자 확인 요청                    ← 제외
    근거 자료 표 (검수용)                     ← 제외

따라서 본문은 "H1 다음부터, 첫 번째 검수용 섹션 직전까지"입니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .richtext import block_text, plain_text, strip_markers

Block = dict[str, Any]

#: 이 문구가 헤딩에 나오면 그 지점부터는 본문이 아닙니다.
REVIEW_MARKERS: tuple[str, ...] = (
    "작성 메타 정보",
    "구조화 제안",
    "셀프 점검 결과",
    "사용자 확인 요청",
    "근거 자료 표",
    "검수용",
    "발행 전 확인",
)

#: 이 제목의 토글은 기획안이므로 본문에 쓰지 않습니다.
GUIDE_TOGGLE_TITLES: tuple[str, ...] = ("콘텐츠 가이드",)

#: 자동화가 남긴 안내 callout을 알아보는 문구.
NOTICE_CALLOUT_HINTS: tuple[str, ...] = (
    "콘텐츠 가이드를 확인",
    "자동 생성 원고",
    "원고 자동화 에이전트",
)

HEADING_TYPES = ("heading_1", "heading_2", "heading_3")


@dataclass
class ImageHint:
    """원고의 '이미지 alt 텍스트 가이드' 한 줄."""

    position: str  # "도입부", "병변 비교표 상단", "클로징" 등
    alt: str


@dataclass
class Extracted:
    body: list[Block] = field(default_factory=list)
    h1: str = ""
    review_sections: dict[str, list[Block]] = field(default_factory=dict)
    image_hints: list[ImageHint] = field(default_factory=list)
    schema_hint: str = ""

    @property
    def is_empty(self) -> bool:
        """본문에 실제 내용이 있는지. 구분선·빈 문단만 남았으면 비어 있는 것으로 봅니다."""
        return not any(_carries_content(b) for b in self.body)


def _carries_content(block: Block) -> bool:
    btype = block.get("type")
    if btype in ("divider", "table_of_contents", "breadcrumb"):
        return False
    if btype == "paragraph":
        return bool(block_text(block).strip())
    return True


def _is_review_heading(block: Block) -> bool:
    """검수용 섹션의 시작점인지 판별합니다."""
    btype = block.get("type")

    if btype in HEADING_TYPES:
        text = strip_markers(block_text(block))
    elif btype == "paragraph":
        # 헤딩이 아니라 굵은 글씨 한 줄로 적힌 검수용 제목도 있습니다.
        nodes = (block.get("paragraph") or {}).get("rich_text") or []
        if not nodes or not all((n.get("annotations") or {}).get("bold") for n in nodes):
            return False
        text = strip_markers(plain_text(nodes))
    else:
        return False

    if not text:
        return False
    return any(marker in text for marker in REVIEW_MARKERS)


def _is_guide_toggle(block: Block) -> bool:
    if block.get("type") != "toggle":
        return False
    title = strip_markers(block_text(block))
    return any(t in title for t in GUIDE_TOGGLE_TITLES)


def _is_notice_callout(block: Block) -> bool:
    if block.get("type") != "callout":
        return False
    text = block_text(block)
    return any(hint in text for hint in NOTICE_CALLOUT_HINTS)


def _is_meta_description_label(block: Block) -> bool:
    if block.get("type") != "paragraph":
        return False
    return strip_markers(block_text(block)) in ("메타 디스크립션", "메타디스크립션")


def extract(blocks: list[Block]) -> Extracted:
    """최상위 블록 목록에서 본문과 검수용 섹션을 분리합니다."""
    result = Extracted()

    # 1) 본문 시작점 — H1 바로 다음.
    start = 0
    for i, block in enumerate(blocks):
        if block.get("type") == "heading_1":
            result.h1 = block_text(block).strip()
            start = i + 1
            break

    # 2) 본문 끝점 — 첫 검수용 섹션 직전.
    end = len(blocks)
    for i in range(start, len(blocks)):
        if _is_review_heading(blocks[i]):
            end = i
            break

    # 3) 본문 구간에서 남은 잡동사니를 걷어냅니다.
    #    (H1이 없는 원고를 대비해 이 필터는 항상 돕니다.)
    body: list[Block] = []
    skip_next_paragraph = False

    for block in blocks[start:end]:
        if skip_next_paragraph and block.get("type") == "paragraph":
            skip_next_paragraph = False
            continue
        skip_next_paragraph = False

        if _is_guide_toggle(block) or _is_notice_callout(block):
            continue
        if block.get("type") == "heading_1":
            # H1은 워드프레스 제목이 대신하므로 본문에 중복해서 넣지 않습니다.
            if not result.h1:
                result.h1 = block_text(block).strip()
            continue
        if _is_meta_description_label(block):
            skip_next_paragraph = True
            continue

        body.append(block)

    result.body = _trim_edges(body)

    # 4) 검수용 섹션은 버리지 않고 헤딩별로 모아둡니다 — ALT·스키마 지침이 여기 있습니다.
    result.review_sections = _split_review_sections(blocks[end:])
    hints, schema_hint = parse_structure_hints(result.review_sections)
    result.image_hints = hints
    result.schema_hint = schema_hint

    return result


def _trim_edges(body: list[Block]) -> list[Block]:
    """앞뒤에 붙은 구분선과 빈 문단을 잘라냅니다."""
    lo, hi = 0, len(body)
    while lo < hi and not _carries_content(body[lo]):
        lo += 1
    while hi > lo and not _carries_content(body[hi - 1]):
        hi -= 1
    return body[lo:hi]


def _split_review_sections(blocks: list[Block]) -> dict[str, list[Block]]:
    sections: dict[str, list[Block]] = {}
    current = ""

    for block in blocks:
        if block.get("type") in HEADING_TYPES or _is_review_heading(block):
            heading = strip_markers(block_text(block))
            if heading:
                current = heading
                sections.setdefault(current, [])
                continue
        if current:
            sections[current].append(block)

    return sections


def _code_spans(block: Block) -> str:
    """블록 안에서 코드 서식이 걸린 부분만 이어붙입니다.

    ALT 가이드가 `백틱`으로 감싸여 오기 때문에, 뒤에 붙은 괄호 주석을 자연스럽게
    떼어낼 수 있는 가장 정확한 방법입니다.
    """
    payload = block.get(block.get("type", ""), {})
    nodes = payload.get("rich_text") or [] if isinstance(payload, dict) else []
    spans = [
        n.get("plain_text", "")
        for n in nodes
        if (n.get("annotations") or {}).get("code")
    ]
    return "".join(spans).strip()


def _clean_alt(text: str) -> str:
    text = text.strip().strip("`").strip()
    # "… (치료 전후 이미지는 사전심의 이슈로 사용 지양)" 같은 꼬리 주석을 떼어냅니다.
    text = re.sub(r"\s*\([^)]{6,}\)\s*$", "", text)
    return text.strip(" .·")


def parse_structure_hints(
    sections: dict[str, list[Block]],
) -> tuple[list[ImageHint], str]:
    """'구조화 제안' 섹션에서 이미지 ALT 가이드와 스키마 제안을 읽어옵니다."""
    target: list[Block] = []
    for name, blocks in sections.items():
        if "구조화 제안" in name:
            target = blocks
            break

    if not target:
        return [], ""

    hints: list[ImageHint] = []
    schema_hint = ""

    def walk(items: list[Block]) -> None:
        nonlocal schema_hint
        for block in items:
            text = block_text(block)
            stripped = strip_markers(text)
            children = block.get("_children") or []

            if "스키마" in stripped and ":" in text and not schema_hint:
                schema_hint = text.split(":", 1)[1].strip()

            is_alt_header = (
                "alt" in stripped.lower() and "가이드" in stripped
            ) or "이미지 alt" in stripped.lower()

            if is_alt_header and children:
                for child in children:
                    hint = _parse_hint_line(child)
                    if hint:
                        hints.append(hint)
                continue

            if children:
                walk(children)

    walk(target)
    return hints, schema_hint


def _parse_hint_line(block: Block) -> ImageHint | None:
    text = block_text(block)
    if not text.strip():
        return None

    # "도입부: `기미 레이저 치료 회차를 상담하는 진료 장면`"
    parts = re.split(r"[:：]", text, maxsplit=1)
    if len(parts) != 2:
        return None

    position = strip_markers(parts[0])
    alt = _code_spans(block) or _clean_alt(parts[1])

    if not position or not alt:
        return None
    return ImageHint(position=position, alt=_clean_alt(alt))
