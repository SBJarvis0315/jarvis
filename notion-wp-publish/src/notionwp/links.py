"""원고 끝의 '참고 자료'·'관련 글' 줄에 실제 링크를 겁니다 (고객사별).

참포도나무병원 숏폼은 글 끝에 이런 줄이 옵니다.

    참고 자료: 대한신경외과학회, 서울아산병원
    관련 글: 신경차단술 · 신경성형술 · 하지 방사통

원고 생성은 이 줄을 **글자로만** 씁니다. 지금까지는 발행 뒤 사람이 워드프레스에서
하나씩 링크를 걸었는데, 그래서 빠지거나(두 줄 다 안 건 글이 여럿), 엇나가거나
('허리디스크' 를 주사치료 글에 걸어 둔 것), 같은 학회를 다른 주소로 거는 일이
생겼습니다. 발행 단계가 걸면 매번 같게 나옵니다.

    links/
      참포도나무병원.json

두 가지를 합니다. 둘 다 **이미 링크가 걸린 줄은 건드리지 않습니다.**

  · 참고 자료 — 기관명을 표(`references`)의 공식 주소로 겁니다. 표에 없는 이름은
    글자 그대로 두고 경고만 남깁니다. 주소를 지어내지 않습니다.
  · 관련 글   — 항목을 **이 고객사 플래너의 게재완료 행** 제목과 맞춰, 그 행의 URL
    속성을 그대로 겁니다. 맞는 행이 없으면 그 항목을 **지웁니다**. 없는 글로 가는
    링크보다 항목 하나 빠지는 편이 낫습니다. 전부 없으면 줄 자체를 지웁니다.

파일이 없는 고객사는 아무 일도 일어나지 않습니다. `tails/`·`posttypes/` 와 같은
방식입니다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .designs import safe_name
from .richtext import plain_text

log = logging.getLogger(__name__)

LINK_DIR = Path(__file__).resolve().parents[2] / "links"

Block = dict[str, Any]

#: 줄머리. 콜론 앞까지입니다. 원고가 쓰는 변형을 전부 받습니다.
DEFAULT_REFERENCE_PREFIXES = ("참고 자료", "참고자료", "출처 및 참고자료", "출처 및 참고 자료", "출처")
DEFAULT_RELATED_PREFIXES = ("관련 글", "관련글", "함께 읽으면 좋은 글", "함께 읽으면 좋은 글")

#: 항목 구분자. 쉼표·가운뎃점·슬래시·세로선.
_SEPARATOR = re.compile(r"\s*[,·/|]\s*")
_HEAD = re.compile(r"^\s*(?:\*\*)?\s*(?P<prefix>[^:：]{1,20}?)\s*(?:\*\*)?\s*[:：]\s*(?P<rest>.+?)\s*$", re.S)


class LinkError(RuntimeError):
    pass


@dataclass
class LinkRules:
    client: str
    #: 기관명 → 공식 주소. 같은 기관의 다른 표기는 여러 키로 적습니다.
    references: dict[str, str] = field(default_factory=dict)
    #: 관련 글 항목을 플래너 게재완료 행에 맞춰 링크할지.
    related: bool = False
    reference_prefixes: tuple[str, ...] = DEFAULT_REFERENCE_PREFIXES
    related_prefixes: tuple[str, ...] = DEFAULT_RELATED_PREFIXES
    note: str = ""

    def reference_url(self, name: str) -> str | None:
        key = _norm(name)
        for known, url in self.references.items():
            if _norm(known) == key:
                return url
        return None


def path_for(client: str, directory: Path | None = None) -> Path:
    return (directory or LINK_DIR) / f"{safe_name(client)}.json"


def load(client: str, directory: Path | None = None) -> LinkRules | None:
    """링크 규칙을 읽습니다. 없으면 None — 대부분의 고객사가 그렇습니다."""
    path = path_for(client, directory)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LinkError(f"링크 규칙을 읽지 못했습니다 ({path}): {exc}") from exc

    references = {str(k).strip(): str(v).strip() for k, v in (raw.get("references") or {}).items()}
    for name, url in references.items():
        if not url.startswith(("http://", "https://")):
            raise LinkError(f"'{name}' 의 주소가 http(s) 로 시작하지 않습니다 ({path})")

    return LinkRules(
        client=raw.get("client", client),
        references=references,
        related=bool(raw.get("related", False)),
        reference_prefixes=tuple(raw.get("reference_prefixes") or DEFAULT_REFERENCE_PREFIXES),
        related_prefixes=tuple(raw.get("related_prefixes") or DEFAULT_RELATED_PREFIXES),
        note=raw.get("note", ""),
    )


# ------------------------------------------------------------------ 적용


Resolver = Callable[[str], str | None]


def apply(
    blocks: list[Block],
    rules: LinkRules | None,
    *,
    resolve_related: Resolver | None = None,
) -> tuple[list[Block], list[str]]:
    """본문 블록을 돌며 두 줄에 링크를 겁니다. (새 블록 목록, 경고) 를 돌려줍니다."""
    if rules is None:
        return blocks, []

    out: list[Block] = []
    warnings: list[str] = []

    for block in blocks:
        if block.get("type") != "paragraph":
            out.append(block)
            continue

        rich = (block.get("paragraph") or {}).get("rich_text") or []
        if any(node.get("href") for node in rich):
            out.append(block)  # 이미 링크가 있으면 사람이든 원고든 그 뜻을 존중합니다.
            continue

        head = _HEAD.match(plain_text(rich))
        if not head:
            out.append(block)
            continue

        prefix = head.group("prefix").strip()
        items = [i for i in _SEPARATOR.split(head.group("rest").strip()) if i]

        if _matches(prefix, rules.reference_prefixes) and rules.references:
            out.append(_relink(block, prefix, items, rules.reference_url, warnings, drop_unresolved=False))
            continue

        if _matches(prefix, rules.related_prefixes) and rules.related and resolve_related:
            rebuilt = _relink(block, prefix, items, resolve_related, warnings, drop_unresolved=True)
            if rebuilt is not None:
                out.append(rebuilt)
            else:
                warnings.append(f"'{prefix}' 줄: 게재된 글과 맞는 항목이 하나도 없어 줄을 뺐습니다")
            continue

        out.append(block)

    return out, warnings


def _relink(
    block: Block,
    prefix: str,
    items: list[str],
    resolve: Resolver,
    warnings: list[str],
    *,
    drop_unresolved: bool,
) -> Block | None:
    """줄머리는 굵게, 항목은 링크로 다시 짭니다. 못 찾은 항목은 규칙대로 둡니다/뺍니다."""
    nodes: list[dict[str, Any]] = [_node(f"{prefix}: ", bold=True)]
    kept = 0

    for n, item in enumerate(items):
        url = resolve(item)
        if url is None:
            if drop_unresolved:
                warnings.append(f"'{prefix}' 줄: '{item}' 에 맞는 게재된 글이 없어 뺐습니다")
                continue
            warnings.append(f"'{prefix}' 줄: '{item}' 의 주소가 표에 없어 글자로 뒀습니다")
            nodes.append(_node(item))
        else:
            nodes.append(_node(item, href=url))
        kept += 1
        if n < len(items) - 1:
            nodes.append(_node(", "))

    if kept == 0 and drop_unresolved:
        return None

    # 마지막 항목이 빠졌으면 구분자가 끝에 남습니다.
    if nodes and nodes[-1]["plain_text"] == ", ":
        nodes.pop()

    rebuilt = dict(block)
    rebuilt["paragraph"] = dict(block.get("paragraph") or {})
    rebuilt["paragraph"]["rich_text"] = nodes
    return rebuilt


def make_related_resolver(
    rows: list[dict[str, Any]],
    *,
    title_prop: str,
    url_prop: str,
    status_prop: str,
    done: str,
    site: str = "",
) -> Resolver:
    """플래너 행에서 '게재완료 + URL 있음' 인 것만 모아, 제목으로 찾는 함수를 만듭니다.

    `site` 를 주면 **그 사이트 주소로 시작하는 URL 만** 씁니다. 플래너에는 네이버
    블로그에 올린 글도 게재완료로 섞여 있는데, 워드프레스 글의 '관련 글'이 네이버로
    가면 안 됩니다.

    맞춤은 두 가지뿐이고, 어느 쪽이든 둘 이상이면 고르지 않습니다.
      ① 제목이 항목과 같다
      ② 제목의 첫 마디(괄호·쉼표·물음표·'이란' 앞)가 항목과 같다
         — '척추관협착증' 은 '척추관협착증이란? 증상·원인…' 으로 가고,
            '척추관 협착증 수술은 언제…' 로는 가지 않습니다
    '제목이 항목으로 시작한다'는 일부러 쓰지 않습니다. 실제 플래너에서 '디스크' 가
    '디스크내장증' 으로, '허리디스크' 가 '허리디스크 주사치료…' 로 가 버립니다 —
    그게 바로 사람이 손으로 걸다 엇나간 경우입니다.
    """
    from . import notion_api as napi

    site_key = site.rstrip("/").lower()
    index: list[tuple[str, str, str, str]] = []  # (정규화 제목, 첫 마디, 원제목, url)
    for row in rows:
        props = row.get("properties") or {}
        if napi.read_select(props.get(status_prop)) != done:
            continue
        url = napi.read_url(props.get(url_prop)).strip()
        title = napi.read_text(props.get(title_prop)).strip()
        if not url or not title:
            continue
        if site_key and not url.lower().startswith(site_key):
            continue
        index.append((_norm(title), _first_clause(title), title, url))

    def pick(urls: list[str]) -> str | None:
        return urls[0] if len(urls) == 1 else None

    def resolve(item: str) -> str | None:
        key = _norm(item)
        if len(key) < 2:
            return None
        return (
            pick([u for k, _, _, u in index if k == key])
            or pick([u for _, f, _, u in index if f == key])
        )

    return resolve


# ------------------------------------------------------------------ 보조


def _matches(prefix: str, candidates: tuple[str, ...]) -> bool:
    key = _norm(prefix)
    return any(_norm(c) == key for c in candidates)


def _first_clause(title: str) -> str:
    """제목의 첫 마디. '허리디스크(요추 추간판 탈출증), 원인…' → '허리디스크'."""
    head = re.split(r"[(（,，?？:：|｜—–\-]", title, maxsplit=1)[0]
    return _norm(head)


def _norm(text: str) -> str:
    """공백·굵게 표시·끝의 물음표/'이란?' 류를 걷어내고 비교합니다."""
    text = re.sub(r"\*+", "", text or "")
    text = re.sub(r"\s+", "", text)
    # '척추관협착증이란' ≒ '척추관협착증'. 물음표가 떨어져 나간 뒤에도 같게 봅니다.
    # '경막외 스테로이드 주사란' 도 같습니다. 물음표가 떨어져 나간 뒤에도 같게 봅니다.
    stripped = re.sub(r"(이란|란)\??$", "", text)
    text = stripped if len(stripped) >= 2 else text
    text = re.sub(r"(은|는)\?$", "", text)
    text = re.sub(r"\?$", "", text)
    return text.strip().lower()


def _node(text: str, *, href: str | None = None, bold: bool = False) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "text",
        "text": {"content": text, "link": {"url": href} if href else None},
        "plain_text": text,
        "href": href,
        "annotations": {"bold": bold, "italic": False, "strikethrough": False,
                        "underline": False, "code": False, "color": "default"},
    }
    return node
