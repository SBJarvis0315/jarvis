"""작업 계획 파일 (plan.json).

스크립트는 이미지를 '볼' 수 없습니다. 그래서 발행을 두 단계로 나눕니다.

    1) prepare  — 이미지를 내려받고 본문 개요와 기본 배치를 plan.json 에 씁니다.
    2) (사람 또는 루틴 안의 Claude가 이미지를 보고 alt 를 채웁니다)
    3) publish  — plan.json 의 alt·배치를 그대로 써서 발행합니다.

plan.json 이 없으면 예전처럼 원고의 ALT 가이드를 폴백으로 씁니다.

부수 효과가 하나 있는데 꽤 유용합니다. prepare 단계에서 이미지를 이미 내려받아
두므로, 발행 시점에 노션 첨부 주소(1시간 만료)를 다시 부를 필요가 없습니다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .richtext import block_text, strip_markers

Block = dict[str, Any]

PLAN_FILENAME = "plan.json"
PREVIEW_MAX_EDGE = 1024
HEADING_TYPES = ("heading_2", "heading_3")

#: 섹션 문맥으로 넘겨줄 본문 발췌 길이. ALT가 글 내용과 맞물리게 하는 용도입니다.
EXCERPT_CHARS = 320


@dataclass
class Section:
    anchor: int  # 이 위치 '앞'에 이미지를 넣습니다 (헤딩 바로 다음)
    level: int
    heading: str
    excerpt: str


@dataclass
class PlannedImage:
    n: int
    original: str  # plan.json 기준 상대 경로 (원본, 업로드용)
    preview: str  # 축소본 (사람·모델이 눈으로 볼 용도)
    anchor: int
    alt: str = ""
    source_name: str = ""
    #: 원고 마커가 남긴 참고 문구. 이미지를 보기 전 글쓴이의 의도를 알려줍니다.
    #: 최종 ALT 는 이미지를 직접 보고 쓰되, 이 문구를 참고할 수 있습니다.
    hint: str = ""


@dataclass
class PagePlan:
    page_id: str
    title: str
    slug: str
    sections: list[Section] = field(default_factory=list)
    images: list[PlannedImage] = field(default_factory=list)
    thumbnail: str = ""
    thumbnail_preview: str = ""
    thumbnail_alt: str = ""
    thumbnail_hint: str = ""

    # ------------------------------------------------------------------ 입출력

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / PLAN_FILENAME
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, directory: Path) -> PagePlan:
        raw = json.loads((directory / PLAN_FILENAME).read_text(encoding="utf-8"))
        return cls(
            page_id=raw["page_id"],
            title=raw.get("title", ""),
            slug=raw.get("slug", ""),
            sections=[Section(**s) for s in raw.get("sections", [])],
            images=[PlannedImage(**i) for i in raw.get("images", [])],
            thumbnail=raw.get("thumbnail", ""),
            thumbnail_preview=raw.get("thumbnail_preview", ""),
            thumbnail_alt=raw.get("thumbnail_alt", ""),
            thumbnail_hint=raw.get("thumbnail_hint", ""),
        )

    @property
    def missing_alts(self) -> list[int]:
        return [img.n for img in self.images if not img.alt.strip()]


def outline(body: list[Block]) -> list[Section]:
    """본문의 헤딩 구조와 각 구간의 앞부분 발췌를 뽑아냅니다."""
    heading_idx = [i for i, b in enumerate(body) if b.get("type") in HEADING_TYPES]

    first_heading = heading_idx[0] if heading_idx else len(body)
    sections: list[Section] = [
        Section(
            anchor=0,
            level=0,
            heading="(도입부)",
            excerpt=_excerpt(body, 0, first_heading),
        )
    ]

    for pos, i in enumerate(heading_idx):
        end = heading_idx[pos + 1] if pos + 1 < len(heading_idx) else len(body)
        sections.append(
            Section(
                anchor=i + 1,
                level=2 if body[i].get("type") == "heading_2" else 3,
                heading=strip_markers(block_text(body[i])),
                excerpt=_excerpt(body, i + 1, end),
            )
        )

    return sections


def _excerpt(body: list[Block], start: int, end: int) -> str:
    parts: list[str] = []
    for block in body[start:end]:
        if block.get("type") in ("paragraph", "bulleted_list_item", "numbered_list_item", "to_do"):
            text = block_text(block).strip()
            if text:
                parts.append(text)
        if sum(len(p) for p in parts) > EXCERPT_CHARS:
            break
    joined = " ".join(parts)
    return joined[:EXCERPT_CHARS].rstrip() + ("…" if len(joined) > EXCERPT_CHARS else "")


def make_preview(source: Path, destination: Path) -> bool:
    """긴 변 기준으로 축소한 미리보기를 만듭니다.

    원본은 2560px 급이라 그대로 보면 낭비가 큽니다. 실패하면 조용히 넘어가고
    원본을 그대로 보게 둡니다 — 미리보기는 편의 기능이지 필수가 아닙니다.
    """
    try:
        from PIL import Image
    except ImportError:
        return False

    try:
        with Image.open(source) as im:
            im = im.convert("RGB")
            im.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE))
            destination.parent.mkdir(parents=True, exist_ok=True)
            im.save(destination, "JPEG", quality=72, optimize=True)
        return True
    except Exception:
        return False


def plan_dir_for(root: Path, page_id: str) -> Path:
    return root / page_id.replace("-", "")
