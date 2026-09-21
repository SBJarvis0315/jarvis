"""글 맨 끝에 늘 붙는 고정 블록 (고객사별).

참포도나무병원 숏폼처럼, 원고와 무관하게 **발행되는 글 맨 아래에 항상 같은
것이 붙어야 하는** 고객사가 있습니다(의료진 프로필 패턴 등). 원고 생성 지침으로는
할 수 없습니다 — 발행 단계가 노션 블록을 보고 워드프레스 블록을 직접 조립하며,
원고에 적힌 마크업은 글자로 이스케이프되기 때문입니다.

그래서 발행 직전에 렌더된 본문 끝에 그대로 이어 붙입니다.

    tails/
      참포도나무병원.json

설정표에 칸을 늘리지 않으려고 저장소에 둡니다. `designs/`·`boards/` 와 같은
방식입니다. 파일이 없는 고객사는 아무것도 붙지 않습니다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .designs import safe_name

log = logging.getLogger(__name__)

TAIL_DIR = Path(__file__).resolve().parents[2] / "tails"


class TailError(RuntimeError):
    pass


@dataclass
class Tail:
    """한 고객사의 고정 꼬리말."""

    client: str
    #: 이 유형의 글에만 붙입니다. 비우면 모든 유형에 붙습니다.
    types: list[str] = field(default_factory=list)
    #: 워드프레스 블록 마크업 그대로. 이스케이프하지 않고 본문 끝에 이어 붙입니다.
    blocks: str = ""
    note: str = ""

    def applies_to(self, page_type: str) -> bool:
        if not self.blocks.strip():
            return False
        return not self.types or page_type in self.types


def path_for(client: str, directory: Path | None = None) -> Path:
    return (directory or TAIL_DIR) / f"{safe_name(client)}.json"


def load(client: str, directory: Path | None = None) -> Tail | None:
    """고정 꼬리말을 읽습니다. 없으면 None — 대부분의 고객사가 그렇습니다."""
    path = path_for(client, directory)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TailError(f"꼬리말 파일을 읽지 못했습니다 ({path}): {exc}") from exc

    blocks = str(raw.get("blocks", "")).strip()
    if not blocks:
        raise TailError(f"꼬리말 파일에 blocks 가 비어 있습니다 ({path})")

    return Tail(
        client=raw.get("client", client),
        types=[str(t) for t in (raw.get("types") or [])],
        blocks=blocks,
        note=raw.get("note", ""),
    )


def append(content: str, tail: Tail | None, page_type: str) -> str:
    """렌더된 본문 끝에 꼬리말을 잇습니다. 붙일 것이 없으면 본문 그대로."""
    if tail is None or not tail.applies_to(page_type):
        return content
    log.info("본문 끝에 고정 블록을 붙입니다 (%s · %s)", tail.client, page_type or "유형 없음")
    return f"{content.rstrip()}\n\n{tail.blocks.strip()}"
