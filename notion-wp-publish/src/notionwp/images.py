"""이미지 처리 — 노션 파일 속성 읽기, 배치 계산, ALT 결정.

배치의 근거는 원고 자체에 있습니다. '🔧 구조화 제안 > 이미지 alt 텍스트 가이드'가
위치와 ALT 문구를 짝지어 알려주므로, 그 위치 라벨을 본문 헤딩에 매칭합니다.

    도입부:          기미 레이저 치료 회차를 상담하는 진료 장면
    병변 비교표 상단: 기미 흑자 검버섯 색소 깊이 비교
    회차 설명 섹션:   색소 레이저 회차별 경과 확인 과정
    클로징:          클리어톤의원 색소 레이저 장비

가이드가 없거나 매칭이 안 되면 H2 구간에 고르게 나눠 넣습니다(결정론적 폴백).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from .extract import ImageHint
from .richtext import block_text, strip_markers

Block = dict[str, Any]

INTRO_WORDS = ("도입", "인트로", "서두", "첫", "상단부")
CLOSING_WORDS = ("클로징", "마무리", "결론", "맺음", "하단")

#: 이 점수 아래면 매칭 실패로 보고 균등 배치로 넘깁니다.
MATCH_THRESHOLD = 0.08

HEADING_TYPES = ("heading_2", "heading_3")


@dataclass
class NotionFile:
    name: str
    url: str


@dataclass
class Placement:
    """본문 리스트에서 index 위치 '앞'에 이미지를 끼워 넣습니다."""

    index: int
    alt: str


def iter_files(prop: dict[str, Any] | None) -> list[NotionFile]:
    """노션 files 속성 → 파일 목록 (업로드 순서 유지)."""
    if not prop:
        return []

    out: list[NotionFile] = []
    for entry in prop.get("files") or []:
        url = ""
        if entry.get("type") == "external":
            url = (entry.get("external") or {}).get("url", "")
        else:
            url = (entry.get("file") or {}).get("url", "")
        if url:
            out.append(NotionFile(name=entry.get("name") or "", url=url))
    return out


def target_filename(slug: str, index: int | None, source_url: str, source_name: str = "") -> str:
    """업로드용 파일명을 슬러그 기반 영문으로 만듭니다.

    노션 원본이 '기미레이저횟수1.jpg' 처럼 한글이라 그대로 올리면 주소가 깨집니다.
    슬러그를 쓰면 이미지 주소도 내용을 담게 됩니다.
    """
    ext = _extension(source_url) or _extension(source_name) or "jpg"
    base = re.sub(r"[^a-z0-9-]+", "-", (slug or "image").lower()).strip("-") or "image"
    suffix = "thumbnail" if index is None else str(index)
    return f"{base}-{suffix}.{ext}"


def _extension(value: str) -> str:
    if not value:
        return ""
    path = urlparse(value).path if "://" in value else value
    ext = posixpath.splitext(unquote(path))[1].lstrip(".").lower()
    return ext if re.fullmatch(r"[a-z0-9]{2,5}", ext or "") else ""


# ------------------------------------------------------------------- 배치 계산


def _bigrams(text: str) -> set[str]:
    condensed = re.sub(r"[\s\W_]+", "", text or "")
    if len(condensed) < 2:
        return {condensed} if condensed else set()
    return {condensed[i : i + 2] for i in range(len(condensed) - 1)}


def _similarity(a: str, b: str) -> float:
    left, right = _bigrams(a), _bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _heading_anchors(body: list[Block]) -> list[tuple[int, str, bool]]:
    """(헤딩 다음 index, 헤딩 텍스트, 그 구간에 표가 있는지) 목록."""
    anchors: list[tuple[int, str, bool]] = []
    heading_idx = [i for i, b in enumerate(body) if b.get("type") in HEADING_TYPES]

    for pos, i in enumerate(heading_idx):
        end = heading_idx[pos + 1] if pos + 1 < len(heading_idx) else len(body)
        has_table = any(b.get("type") == "table" for b in body[i:end])
        anchors.append((i + 1, strip_markers(block_text(body[i])), has_table))

    return anchors


def plan_placements(
    body: list[Block],
    hints: list[ImageHint],
    image_count: int,
    *,
    fallback_alt_prefix: str = "",
) -> list[Placement]:
    """이미지 개수만큼 (삽입 위치, ALT) 를 만들어 돌려줍니다."""
    if image_count <= 0 or not body:
        return []

    anchors = _heading_anchors(body)
    used: set[int] = set()
    resolved: list[int | None] = []

    # 1) 가이드 라벨을 헤딩에 매칭.
    for hint in hints[:image_count]:
        label = hint.position
        index: int | None = None

        if any(w in label for w in INTRO_WORDS):
            index = 0
        elif any(w in label for w in CLOSING_WORDS) and anchors:
            index = anchors[-1][0]
        elif anchors:
            wants_table = "표" in label
            scored = [
                (
                    _similarity(label, text) + (0.25 if wants_table and has_table else 0.0),
                    idx,
                )
                for idx, text, has_table in anchors
                if idx not in used
            ]
            if scored:
                best_score, best_idx = max(scored, key=lambda s: s[0])
                if best_score >= MATCH_THRESHOLD:
                    index = best_idx

        if index is not None:
            used.add(index)
        resolved.append(index)

    # 2) 가이드보다 이미지가 많으면 남는 구간에 채웁니다.
    while len(resolved) < image_count:
        resolved.append(None)

    # 3) 매칭 실패분과 초과분을 아직 비어 있는 구간에 고르게 배분.
    free = [idx for idx, _, _ in anchors if idx not in used] or [len(body)]
    spare = iter(_spread(free, resolved.count(None)))
    positions = [idx if idx is not None else next(spare, len(body)) for idx in resolved]

    # 4) 문서 순서를 지키기 위해 위치만 정렬합니다.
    #    ALT는 가이드 순서를 그대로 유지해야 이미지와 설명이 어긋나지 않습니다.
    positions.sort()

    alts = [h.alt for h in hints[:image_count]]
    while len(alts) < image_count:
        alts.append("")

    placements: list[Placement] = []
    for pos, alt in zip(positions, alts, strict=True):
        placements.append(
            Placement(index=pos, alt=alt or _derive_alt(body, pos, fallback_alt_prefix))
        )
    return placements


def _spread(slots: list[int], count: int) -> list[int]:
    """빈 구간 목록에서 count 개를 고르게 골라냅니다."""
    if count <= 0 or not slots:
        return []
    if count >= len(slots):
        return list(slots)
    step = len(slots) / count
    return [slots[min(len(slots) - 1, int(i * step))] for i in range(count)]


def _derive_alt(body: list[Block], index: int, prefix: str) -> str:
    """가이드에 없는 이미지는 바로 위 헤딩 문구에서 ALT를 만듭니다.

    가이드가 요구하는 '글 안에서 이미지를 설명하는 표현'에 가장 가까운 근사치입니다.
    """
    for i in range(min(index, len(body)) - 1, -1, -1):
        if body[i].get("type") in HEADING_TYPES:
            heading = strip_markers(block_text(body[i]))
            if heading:
                return heading
    return prefix or "본문 이미지"
