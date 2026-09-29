"""플래너의 '게시판' 을 워드프레스 글 종류로 잇습니다 (고객사별).

대부분의 고객사는 일반 글(post)에 카테고리를 달아 올립니다. 그런데 개발사가
'용어사전' 같은 **별도 글 종류**를 따로 만들어 둔 사이트가 있습니다
(비컴성형외과 glossary). 메뉴는 일반 카테고리와 똑같이 생겼지만 속이 달라서,
일반 글로 올리면 그 섹션에 들어가지 않습니다.

플래너에는 이미 '게시판' 칸이 있고 거기에 `용어사전` 이 적혀 있습니다.
그 값을 글 종류로 잇는 대응표를 고객사별로 둡니다.

    posttypes/
      비컴성형외과.json

설정표에도 플래너에도 칸을 늘리지 않습니다. `designs/`·`tails/`·`certs/` 와
같은 방식입니다. 파일이 없거나 게시판 값이 표에 없으면 지금까지처럼
일반 글 + 일반 카테고리로 올라갑니다.

어떤 글 종류가 있는지는 브리지 플러그인 1.1.0 의 `/ping` 이 알려 줍니다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .designs import safe_name

log = logging.getLogger(__name__)

POSTTYPE_DIR = Path(__file__).resolve().parents[2] / "posttypes"


class PostTypeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    """글을 올릴 곳. 기본값은 워드프레스 표준 글과 카테고리입니다."""

    rest_base: str = "posts"
    taxonomy_rest_base: str = "categories"
    #: 이 글 종류에서 분류를 담는 필드 이름. 표준 글은 'categories' 입니다.
    taxonomy_field: str = "categories"
    label: str = ""

    @property
    def posts_path(self) -> str:
        return f"/wp/v2/{self.rest_base}"

    @property
    def taxonomy_path(self) -> str:
        return f"/wp/v2/{self.taxonomy_rest_base}"

    @property
    def is_default(self) -> bool:
        return self.rest_base == "posts" and self.taxonomy_rest_base == "categories"


DEFAULT = Target()


@dataclass
class Routing:
    """한 고객사의 '게시판' → 글 종류 대응표."""

    client: str
    boards: dict[str, Target]
    note: str = ""

    def target_for(self, board: str) -> Target:
        return self.boards.get((board or "").strip(), DEFAULT)


def path_for(client: str, directory: Path | None = None) -> Path:
    return (directory or POSTTYPE_DIR) / f"{safe_name(client)}.json"


def load(client: str, directory: Path | None = None) -> Routing | None:
    """대응표를 읽습니다. 없으면 None — 대부분의 고객사가 그렇습니다."""
    path = path_for(client, directory)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PostTypeError(f"글 종류 대응표를 읽지 못했습니다 ({path}): {exc}") from exc

    boards: dict[str, Target] = {}
    for board, spec in (raw.get("boards") or {}).items():
        rest_base = str(spec.get("rest_base", "")).strip()
        if not rest_base:
            raise PostTypeError(f"'{board}' 에 rest_base 가 없습니다 ({path})")
        taxonomy = str(spec.get("taxonomy_rest_base", "")).strip()
        boards[board.strip()] = Target(
            rest_base=rest_base,
            taxonomy_rest_base=taxonomy or "categories",
            taxonomy_field=str(spec.get("taxonomy_field", "")).strip()
            or (taxonomy or "categories"),
            label=str(spec.get("label", "")).strip() or board.strip(),
        )

    return Routing(client=raw.get("client", client), boards=boards, note=raw.get("note", ""))


def target_for(routing: Routing | None, board: str) -> Target:
    """대응표가 없으면 기본(일반 글 + 카테고리)."""
    if routing is None:
        return DEFAULT
    target = routing.target_for(board)
    if not target.is_default:
        log.info("'%s' → 글 종류 %s / 분류 %s", board, target.rest_base, target.taxonomy_rest_base)
    return target
