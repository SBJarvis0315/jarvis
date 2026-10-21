"""글 작성자 지정 (고객사별).

발행 스크립트는 워드프레스에 **우리 작업 계정(Growth)** 으로 로그인합니다. 고객사
계정은 공유받지 못하는 경우가 대부분이라 그렇습니다. 그대로 두면 모든 글의 작성자가
작업 계정으로 찍히는데, 저자명은 GEO·AEO 에서 중요한 신호이므로 그러면 안 됩니다.

그래서 고객사마다 **누구 이름으로 올릴지**를 저장소에 적어 둡니다.

    authors/
      지혜로운 필라테스.json     {"client": "지혜로운 필라테스", "author": "이지혜"}

`author` 는 그 사이트 워드프레스 사용자의 표시 이름·사용자명(slug)·숫자 ID 중
무엇이든 됩니다. 설정표에 칸을 늘리지 않으려고 `tails/`·`designs/` 처럼 저장소에 둡니다.

**지정이 없으면 그 고객사는 발행하지 않습니다.** 작업 계정 이름으로 조용히 올라가는
것이 가장 나쁜 결과이기 때문입니다. 지정된 사용자의 이름이나 사용자명(slug)에 `growth` 가
들어 있어도 거부합니다. 고객사 사이트에 따라 로그인 계정의 표시 이름이 고객사 이름이어도
사용자명은 `growth…` 이고, 그 사용자명이 저자 주소(/author/…)로 노출되기 때문입니다. 막히면 그 사이트의 사용자 목록을 메시지에 함께 보여 줍니다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .designs import safe_name

log = logging.getLogger(__name__)

AUTHOR_DIR = Path(__file__).resolve().parents[2] / "authors"

#: 작업 계정으로 보는 이름 조각. 이 이름의 사용자는 저자로 쓰지 않습니다.
WORK_ACCOUNT_MARKERS = ("growth",)


class AuthorError(RuntimeError):
    pass


@dataclass
class Author:
    """한 고객사의 글 작성자."""

    client: str
    #: 표시 이름 · 사용자명 · 숫자 ID 중 하나.
    author: str
    note: str = ""


def path_for(client: str, directory: Path | None = None) -> Path:
    return (directory or AUTHOR_DIR) / f"{safe_name(client)}.json"


def load(client: str, directory: Path | None = None) -> Author | None:
    """작성자 지정을 읽습니다. 파일이 없으면 None — 그 고객사는 발행이 막힙니다."""
    path = path_for(client, directory)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthorError(f"작성자 파일을 읽지 못했습니다 ({path}): {exc}") from exc

    author = str(raw.get("author", "")).strip()
    if not author:
        raise AuthorError(f"작성자 파일에 author 가 비어 있습니다 ({path})")
    return Author(client=raw.get("client", client), author=author, note=raw.get("note", ""))


def is_work_account(user: dict[str, Any]) -> bool:
    text = f"{user.get('name', '')} {user.get('slug', '')}".lower()
    return any(m in text for m in WORK_ACCOUNT_MARKERS)


def resolve(wp: Any, spec: Author | None, client: str) -> int:
    """지정된 작성자의 워드프레스 사용자 ID. 규칙을 어기면 AuthorError.

    발행을 시작하기 전에 한 번 부르세요. 글을 하나라도 만든 뒤에 알게 되면
    이미 작업 계정 이름으로 올라간 글이 남습니다.
    """
    me = wp.current_user()

    def candidates() -> str:
        try:
            names = [
                f"{u.get('name')}(slug {u.get('slug')}, id {u.get('id')})"
                for u in wp.list_users()
                if not is_work_account(u)
            ]
        except Exception:  # noqa: BLE001 - 안내용이라 실패해도 본문 오류가 우선입니다.
            names = []
        return ", ".join(names) if names else "(조회하지 못했습니다)"

    if spec is None:
        raise AuthorError(
            f"'{client}' 의 글 작성자가 지정되지 않아 발행하지 않습니다. "
            f"authors/{safe_name(client)}.json 에 author 를 적어 주세요. "
            f"작업 계정(로그인: {me.get('name')}) 외에 이 사이트에 있는 사용자: {candidates()}"
        )

    user = wp.find_user(spec.author)
    if user is None:
        raise AuthorError(
            f"작성자 '{spec.author}' 를 워드프레스에서 찾지 못했습니다 ('{client}'). "
            f"쓸 수 있는 사용자: {candidates()}"
        )
    if is_work_account(user):
        raise AuthorError(
            f"작성자 '{spec.author}' 는 작업 계정입니다 ('{client}', 로그인: {me.get('name')}). "
            f"저자명은 작업 계정이 아닌 사용자여야 합니다. 쓸 수 있는 사용자: {candidates()}"
        )
    return int(user["id"])
