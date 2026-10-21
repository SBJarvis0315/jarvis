"""글 작성자 정하기.

발행 스크립트는 워드프레스에 **우리 작업 계정(Growth)** 으로 로그인합니다. 고객사
계정은 공유받지 못하는 경우가 대부분이라 그렇습니다. 그대로 두면 글의 작성자가
Growth 로 찍히는데, 저자명은 GEO·AEO 에서 중요한 신호라 그러면 안 됩니다.

그래서 **표시 이름에 `growth` 가 들어간 사용자는 절대 저자로 쓰지 않습니다.**
사람이 미리 정해 줄 필요는 없습니다. 아래 순서로 스크립트가 알아서 고릅니다.

    1. authors/<고객사>.json 의 author 가 있으면 그 사용자 (직접 정하고 싶을 때만)
    2. 로그인 계정의 표시 이름이 Growth 가 아니면 그 계정
       (고객사 이름이나 대표원장 이름으로 만들어 둔 계정이 이 경우입니다)
    3. 아니면 그 사이트에서 Growth 가 아닌 사용자 중 ID 가 가장 작은 사용자
       (보통 사이트를 처음 만든 계정)
    4. Growth 밖에 없으면 어쩔 수 없이 로그인 계정(Growth)으로 올립니다. 멈추지 않고,
       대신 실행 로그에 경고를 남깁니다 — 사이트에 저자용 사용자를 만들면 다음 글부터 바뀝니다

    authors/
      지혜로운 필라테스.json     {"client": "지혜로운 필라테스", "author": "이지혜"}

`author` 는 그 사이트 워드프레스 사용자의 표시 이름·사용자명(slug)·숫자 ID 중
무엇이든 됩니다. 설정표에 칸을 늘리지 않으려고 `tails/`·`designs/` 처럼 저장소에 둡니다.

주의: 저자 주소(/author/<사용자명>/)에는 표시 이름이 아니라 사용자명이 노출됩니다.
로그인 계정의 사용자명이 `growth…` 이면 표시 이름이 괜찮아도 주소에는 그대로 보이므로,
그런 사이트는 파일로 사용자명이 깨끗한 사용자를 직접 지정하는 편이 낫습니다.
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
class Choice:
    """고른 작성자와, 사람이 알아야 할 사정(경고)."""

    user_id: int
    warning: str = ""


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
    """표시 이름에 작업 계정 표시가 들어 있는가. 저자명으로 보이는 것은 표시 이름입니다."""
    text = str(user.get("name", "")).lower()
    return any(m in text for m in WORK_ACCOUNT_MARKERS)


def resolve(wp: Any, spec: Author | None, client: str) -> Choice:
    """글에 올릴 작성자. Growth 가 아닌 사용자를 우선하고, 없으면 로그인 계정으로 올립니다.

    발행을 시작하기 전에 한 번 부르세요. 지정이 잘못됐거나 쓸 사용자가 없어도 발행은
    멈추지 않습니다. 대신 `Choice.warning` 에 이유가 담기니 실행 로그에 남기세요.
    """
    me = wp.current_user()
    users = wp.list_users()
    usable = [u for u in users if not is_work_account(u)]

    def listing() -> str:
        return ", ".join(f"{u.get('name')}(slug {u.get('slug')}, id {u.get('id')})" for u in users) or "(없음)"

    warning = ""
    if spec is not None:
        user = wp.find_user(spec.author)
        if user is None:
            warning = (
                f"authors/ 에 적은 작성자 '{spec.author}' 를 워드프레스에서 찾지 못해 "
                f"자동으로 골랐습니다. 이 사이트의 사용자: {listing()}"
            )
        elif is_work_account(user):
            warning = (
                f"authors/ 에 적은 작성자 '{spec.author}' 는 작업 계정이라 쓰지 않고 "
                f"자동으로 골랐습니다. 이 사이트의 사용자: {listing()}"
            )
        else:
            log.info("[%s] 작성자(지정): %s", client, user.get("name"))
            return Choice(int(user["id"]))

    if not usable:
        warning = (
            warning
            or f"'{client}' 사이트에 Growth 가 아닌 사용자가 없어 로그인 계정"
            f"({me.get('name')})으로 올렸습니다. 저자명이 Growth 로 보입니다. "
            "워드프레스에 대표원장·담당자 이름의 사용자를 만들면 다음 글부터 바뀝니다"
        )
        log.warning("[%s] %s", client, warning)
        return Choice(int(me["id"]), warning)

    mine = next((u for u in usable if u.get("id") == me.get("id")), None)
    user = mine or min(usable, key=lambda u: int(u.get("id", 0)))
    log.info(
        "[%s] 작성자(자동): %s (%s)",
        client,
        user.get("name"),
        "로그인 계정" if mine else "Growth 가 아닌 사용자 중 가장 오래된 계정",
    )
    if warning:
        log.warning("[%s] %s", client, warning)
    return Choice(int(user["id"]), warning)
