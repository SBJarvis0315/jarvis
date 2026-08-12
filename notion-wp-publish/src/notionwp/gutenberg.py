"""노션 블록 → 워드프레스 구텐베르크 마크업.

내부 가이드의 ①·② 단계를 코드로 옮긴 부분입니다.
  ① 공백  → H2 앞에 wp:spacer 를 자동 삽입 (사람이 /SPACE 를 누르던 작업)
  ② H 태그 → 노션 heading_2/3 을 그대로 h2/h3 로 옮김.
             붙여넣기 과정이 없으므로 H 태그가 흐트러질 여지가 없습니다.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from .richtext import to_html

Block = dict[str, Any]

#: 본문에 끼워 넣는 이미지용 가상 블록 타입.
WP_IMAGE = "_wp_image"

LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")

# 체크박스는 워드프레스에서 일반 불릿으로 내보냅니다.
_LIST_FAMILY = {"to_do": "bulleted_list_item"}


@dataclass
class RenderOptions:
    spacer_height: int = 20
    spacer_before_headings: bool = True
    center_tables: bool = True


def image_block(*, url: str, media_id: int, alt: str, caption: str = "") -> Block:
    """업로드가 끝난 이미지를 본문에 끼워 넣기 위한 가상 블록."""
    return {
        "object": "block",
        "type": WP_IMAGE,
        WP_IMAGE: {"url": url, "id": media_id, "alt": alt, "caption": caption},
    }


def render(blocks: list[Block], options: RenderOptions | None = None) -> str:
    opts = options or RenderOptions()
    out: list[str] = []
    i = 0
    seen_heading = False

    while i < len(blocks):
        block = blocks[i]
        btype = block.get("type")

        # 리스트는 연속된 항목을 하나의 wp:list 로 묶어야 합니다.
        if btype in LIST_TYPES:
            group, i = _collect_list(blocks, i)
            out.append(_render_list(group, opts))
            continue

        if btype in ("heading_2", "heading_3") and opts.spacer_before_headings and seen_heading:
            out.append(_spacer(opts.spacer_height))

        if btype in ("heading_1", "heading_2", "heading_3"):
            seen_heading = True

        chunk = _render_block(block, opts)
        if chunk:
            out.append(chunk)
        i += 1

    return "\n\n".join(c for c in out if c)


# ---------------------------------------------------------------- 블록별 렌더러


def _render_block(block: Block, opts: RenderOptions) -> str:
    btype = block.get("type", "")
    payload = block.get(btype) or {}
    children = block.get("_children") or []

    if btype == WP_IMAGE:
        return _render_image(payload)

    if btype == "paragraph":
        inner = to_html(payload.get("rich_text"))
        if not inner.strip():
            return ""
        return _wrap("paragraph", f"<p>{inner}</p>")

    if btype in ("heading_1", "heading_2", "heading_3"):
        # 워드프레스 글 제목이 H1을 차지하므로 본문 H1은 H2로 낮춥니다.
        level = {"heading_1": 2, "heading_2": 2, "heading_3": 3}[btype]
        inner = to_html(payload.get("rich_text"))
        attrs = "" if level == 2 else f' {{"level":{level}}}'
        return (
            f"<!-- wp:heading{attrs} -->\n"
            f'<h{level} class="wp-block-heading">{inner}</h{level}>\n'
            f"<!-- /wp:heading -->"
        )

    if btype == "quote":
        # core/quote 는 내부에 '블록'이 들어갑니다. 생 <p> 를 넣으면
        # 에디터에서 "예기치 않거나 잘못된 콘텐츠" 경고가 뜹니다.
        inner = _paragraph(to_html(payload.get("rich_text")))
        inner += _render_children(children, opts)
        return _wrap("quote", f'<blockquote class="wp-block-quote">{inner}</blockquote>')

    if btype == "callout":
        # 본문에 남은 callout은 인용 박스로 옮깁니다.
        icon = (payload.get("icon") or {}).get("emoji", "")
        prefix = f"{html.escape(icon)} " if icon else ""
        inner = _paragraph(f"{prefix}{to_html(payload.get('rich_text'))}")
        inner += _render_children(children, opts)
        return _wrap("quote", f'<blockquote class="wp-block-quote">{inner}</blockquote>')

    if btype == "code":
        text = "".join(n.get("plain_text", "") for n in payload.get("rich_text") or [])
        escaped = html.escape(text, quote=False)
        return _wrap("code", f'<pre class="wp-block-code"><code>{escaped}</code></pre>')

    if btype == "divider":
        return (
            '<!-- wp:separator -->\n'
            '<hr class="wp-block-separator has-alpha-channel-opacity"/>\n'
            "<!-- /wp:separator -->"
        )

    if btype == "table":
        return _render_table(block, opts)

    if btype == "toggle":
        summary = to_html(payload.get("rich_text"))
        inner = _render_children(children, opts)
        return _wrap(
            "details",
            f'<details class="wp-block-details"><summary>{summary}</summary>{inner}</details>',
        )

    if btype in ("column_list", "column", "synced_block"):
        # 레이아웃 블록은 펼쳐서 내용만 살립니다.
        return render(children, opts) if children else ""

    if btype == "image":
        # 노션 본문에 직접 박힌 이미지. 업로드 단계에서 이미 치환되었어야 하지만,
        # 남아 있다면 만료되는 노션 URL을 그대로 쓰지 않고 건너뜁니다.
        return ""

    # 알 수 없는 블록은 평문이라도 살립니다.
    inner = to_html(payload.get("rich_text")) if isinstance(payload, dict) else ""
    return _wrap("paragraph", f"<p>{inner}</p>") if inner.strip() else ""


def _paragraph(inner: str) -> str:
    """구텐베르크 문단 '블록'. quote·details 안에는 이 형태로 넣어야 합니다."""
    return f"<!-- wp:paragraph -->\n<p>{inner}</p>\n<!-- /wp:paragraph -->"


def _render_children(children: list[Block], opts: RenderOptions) -> str:
    if not children:
        return ""
    nested = RenderOptions(
        spacer_height=opts.spacer_height,
        spacer_before_headings=False,
        center_tables=opts.center_tables,
    )
    return "\n" + render(children, nested) + "\n"


def _wrap(name: str, body: str) -> str:
    return f"<!-- wp:{name} -->\n{body}\n<!-- /wp:{name} -->"


def _spacer(height: int) -> str:
    return (
        f'<!-- wp:spacer {{"height":"{height}px"}} -->\n'
        f'<div style="height:{height}px" aria-hidden="true" class="wp-block-spacer"></div>\n'
        f"<!-- /wp:spacer -->"
    )


def _render_image(payload: dict[str, Any]) -> str:
    media_id = payload.get("id")
    url = html.escape(payload.get("url", ""), quote=True)
    alt = html.escape(payload.get("alt", ""), quote=True)
    caption = payload.get("caption") or ""

    figcaption = (
        f'<figcaption class="wp-element-caption">{html.escape(caption, quote=False)}</figcaption>'
        if caption
        else ""
    )

    return (
        f'<!-- wp:image {{"id":{int(media_id)},"sizeSlug":"large","linkDestination":"none"}} -->\n'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{url}" alt="{alt}" class="wp-image-{int(media_id)}"/>{figcaption}</figure>\n'
        f"<!-- /wp:image -->"
    )


# ------------------------------------------------------------------ 리스트/표


def _collect_list(blocks: list[Block], start: int) -> tuple[list[Block], int]:
    """같은 종류의 리스트 항목이 이어지는 구간을 잘라냅니다."""
    kind = blocks[start].get("type")
    family = _LIST_FAMILY.get(kind, kind)

    group: list[Block] = []
    i = start
    while i < len(blocks):
        btype = blocks[i].get("type")
        if _LIST_FAMILY.get(btype, btype) != family:
            break
        group.append(blocks[i])
        i += 1
    return group, i


def _render_list(group: list[Block], opts: RenderOptions) -> str:
    ordered = group[0].get("type") == "numbered_list_item"
    tag = "ol" if ordered else "ul"
    attrs = ' {"ordered":true}' if ordered else ""

    items: list[str] = []
    for block in group:
        payload = block.get(block.get("type", "")) or {}
        inner = to_html(payload.get("rich_text"))
        nested = ""
        children = block.get("_children") or []
        if children:
            sub = [c for c in children if c.get("type") in LIST_TYPES]
            if sub:
                nested = "\n" + _render_list(sub, opts) + "\n"
        items.append(
            f"<!-- wp:list-item -->\n<li>{inner}{nested}</li>\n<!-- /wp:list-item -->"
        )

    body = "\n".join(items)
    return (
        f"<!-- wp:list{attrs} -->\n"
        f'<{tag} class="wp-block-list">\n{body}\n</{tag}>\n'
        f"<!-- /wp:list -->"
    )


def _render_table(block: Block, opts: RenderOptions) -> str:
    """core/table 이 스스로 저장하는 형태를 그대로 흉내 냅니다.

    구텐베르크의 블록 검증은 매우 엄격해서, 같은 모양이어도 마크업이 조금만
    달라지면 에디터에서 "예기치 않거나 잘못된 콘텐츠" 경고가 뜹니다.
    아래 두 가지가 코어 규칙입니다.

      · 가운데 정렬은 인라인 style 이 아니라
        class="has-text-align-center" + data-align="center" 로 저장됩니다.
      · hasFixedLayout 의 기본값이 true 라서, 지정하지 않으면 코어는
        <table class="has-fixed-layout"> 을 기대합니다. 열 너비를 내용에
        맞추려면 false 를 명시해야 합니다.
    """
    payload = block.get("table") or {}
    rows = [c for c in (block.get("_children") or []) if c.get("type") == "table_row"]
    if not rows:
        return ""

    has_header = bool(payload.get("has_column_header"))
    align = ' class="has-text-align-center" data-align="center"' if opts.center_tables else ""

    def cells(row: Block, tag: str) -> str:
        scope = ' scope="col"' if tag == "th" else ""
        out = [
            f"<{tag}{align}{scope}>{to_html(cell)}</{tag}>"
            for cell in (row.get("table_row") or {}).get("cells") or []
        ]
        return "<tr>" + "".join(out) + "</tr>"

    parts = []
    body_rows = rows

    if has_header:
        parts.append("<thead>" + cells(rows[0], "th") + "</thead>")
        body_rows = rows[1:]

    if body_rows:
        parts.append("<tbody>" + "".join(cells(r, "td") for r in body_rows) + "</tbody>")

    return (
        '<!-- wp:table {"hasFixedLayout":false} -->\n'
        f'<figure class="wp-block-table"><table>{"".join(parts)}</table></figure>\n'
        "<!-- /wp:table -->"
    )
