"""노션 블록 → 자체 게시판용 평범한 HTML.

워드프레스는 구텐베르크 블록 주석이 필요하지만, 자체 홈페이지 게시판(제로클리닉
같은 곳)은 에디터의 코드 보기(`</>`)에 붙여 넣는 맨 HTML 입니다. 팀이 손으로
올릴 때 굳힌 형식을 그대로 따릅니다 — 실제 발행된 글의 소스가 기준입니다.

    <title>…</title>
    <meta name="description" content="…">
    <h1 style="font-size: 20px; margin-bottom: 14px;">…</h1>
    <p>…</p>
    <h2 style="font-size: 18px; margin-top: 28px; margin-bottom: 14px;">…</h2>
    <table><thead>…</thead><tbody>…</tbody></table>
    <p><br></p><div><img src="/files/editor/….jpg" alt="…"></div>

팀이 겪은 함정도 여기서 걸러냅니다.

  · 헤딩 간격은 <br> 이 아니라 인라인 margin 으로 줍니다. 텍스트 보기에서 엔터를
    치면 h 태그가 씹힙니다.
  · <ul>/<ol> 은 사이트 템플릿에서 서식이 깨져 <p> 로 풉니다.
  · 이모지는 ✅ ➡️ 정도만 살아남습니다. 원고가 알아서 지키는 몫이라 여기서
    바꾸지는 않습니다.
"""

from __future__ import annotations

import html
from typing import Any

from .gutenberg import LIST_TYPES, WP_IMAGE, WP_VIDEO
from .richtext import to_html

Block = dict[str, Any]

H1_STYLE = "font-size: 20px; margin-bottom: 14px;"
H2_STYLE = "font-size: 18px; margin-top: 28px; margin-bottom: 14px;"
H3_STYLE = "font-size: 16px; margin-top: 22px; margin-bottom: 10px;"

BULLET = "•"


def render(
    body: list[Block],
    *,
    title: str,
    meta_title: str = "",
    meta_description: str = "",
) -> str:
    """본문 블록 전체를 게시판에 붙일 HTML 한 덩이로 만듭니다."""
    head = [
        f"<title>{html.escape(meta_title or title, quote=False)}</title>",
        f'<meta name="description" content="{html.escape(meta_description, quote=True)}">',
        "",
        f'<h1 style="{H1_STYLE}">{html.escape(title, quote=False)}</h1>',
    ]
    return "\n".join(head) + "\n\n" + render_blocks(body)


def render_blocks(blocks: list[Block]) -> str:
    out: list[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.get("type") in LIST_TYPES:
            group, i = _collect_list(blocks, i)
            out.append(_render_list(group))
            continue
        chunk = _render_block(block)
        if chunk:
            out.append(chunk)
        i += 1
    return "\n\n".join(c for c in out if c)


# ---------------------------------------------------------------- 블록별


def _render_block(block: Block) -> str:
    btype = block.get("type", "")
    payload = block.get(btype) or {}
    children = block.get("_children") or []

    if btype == WP_IMAGE:
        # 게시판 서버에 올라간 이미지. 팀 형식대로 빈 줄 하나를 앞에 둡니다.
        src = html.escape(payload.get("url", ""), quote=True)
        alt = html.escape(payload.get("alt", ""), quote=True)
        return f'<p><br></p><div><img src="{src}" alt="{alt}"></div>'

    if btype == "paragraph":
        inner = to_html(payload.get("rich_text"))
        if not inner.strip():
            return ""
        return f"<p>{inner}</p>" + _children(children)

    if btype in ("heading_1", "heading_2"):
        # 글 제목이 H1 을 차지하므로 본문 H1 은 H2 로 낮춥니다.
        return f'<h2 style="{H2_STYLE}">{to_html(payload.get("rich_text"))}</h2>'

    if btype == "heading_3":
        return f'<h3 style="{H3_STYLE}">{to_html(payload.get("rich_text"))}</h3>'

    if btype == "quote":
        return f"<blockquote><p>{to_html(payload.get('rich_text'))}</p>{_children(children)}</blockquote>"

    if btype == "callout":
        icon = (payload.get("icon") or {}).get("emoji", "")
        prefix = f"{html.escape(icon)} " if icon else ""
        return f"<p>{prefix}{to_html(payload.get('rich_text'))}</p>" + _children(children)

    if btype == "code":
        text = "".join(n.get("plain_text", "") for n in payload.get("rich_text") or [])
        return f"<pre>{html.escape(text, quote=False)}</pre>"

    if btype == "divider":
        # 구분선은 사이트 템플릿마다 모양이 달라 빈 줄로 대신합니다.
        return "<p><br></p>"

    if btype == "table":
        return _render_table(block)

    if btype == "toggle":
        summary = to_html(payload.get("rich_text"))
        return f"<p><strong>{summary}</strong></p>" + _children(children)

    if btype in ("column_list", "column", "synced_block"):
        return render_blocks(children) if children else ""

    if btype == WP_VIDEO:
        url = html.escape(payload.get("url", ""), quote=True)
        note = html.escape(payload.get("note") or "영상으로 보기", quote=False)
        return f'<p>▶ <a href="{url}" target="_blank">{note}</a></p>'

    if btype == "image":
        # 노션에 직접 박힌 이미지는 주소가 1시간 뒤 만료됩니다. 쓰지 않습니다.
        return ""

    inner = to_html(payload.get("rich_text")) if isinstance(payload, dict) else ""
    return f"<p>{inner}</p>" if inner.strip() else ""


def _children(children: list[Block]) -> str:
    if not children:
        return ""
    return "\n" + render_blocks(children)


# ------------------------------------------------------------------ 리스트/표


def _collect_list(blocks: list[Block], start: int) -> tuple[list[Block], int]:
    group: list[Block] = []
    i = start
    while i < len(blocks) and blocks[i].get("type") in LIST_TYPES:
        group.append(blocks[i])
        i += 1
    return group, i


def _render_list(group: list[Block], depth: int = 0) -> str:
    """리스트 항목을 <p> 한 줄씩으로 풉니다.

    사이트 템플릿이 <ul>/<ol> 서식을 깨뜨려 팀이 <p> 로 바꿔 올리던 것을 그대로
    따릅니다. 번호 목록은 번호를 글자로 붙이고, 들여쓰기는 공백으로 흉내 냅니다.
    """
    indent = "&nbsp;" * 4 * depth
    lines: list[str] = []
    number = 0

    for block in group:
        btype = block.get("type", "")
        payload = block.get(btype) or {}
        inner = to_html(payload.get("rich_text"))

        if btype == "numbered_list_item":
            number += 1
            marker = f"{number}."
        elif btype == "to_do":
            marker = "✅" if payload.get("checked") else BULLET
        else:
            marker = BULLET if depth == 0 else "-"

        lines.append(f"<p>{indent}{marker} {inner}</p>")

        nested = [c for c in (block.get("_children") or []) if c.get("type") in LIST_TYPES]
        if nested:
            lines.append(_render_list(nested, depth + 1))

    return "\n".join(lines)


def _render_table(block: Block) -> str:
    payload = block.get("table") or {}
    rows = [c for c in (block.get("_children") or []) if c.get("type") == "table_row"]
    if not rows:
        return ""

    def cells(row: Block, tag: str) -> str:
        parts = [
            f"<{tag}>{to_html(cell)}</{tag}>"
            for cell in (row.get("table_row") or {}).get("cells") or []
        ]
        return "<tr>\n" + "\n".join(parts) + "\n</tr>"

    body_rows = rows
    out = ["<table>"]
    if payload.get("has_column_header"):
        out.append("<thead>\n" + cells(rows[0], "th") + "\n</thead>")
        body_rows = rows[1:]
    if body_rows:
        out.append("<tbody>\n" + "\n".join(cells(r, "td") for r in body_rows) + "\n</tbody>")
    out.append("</table>")
    return "\n".join(out)
