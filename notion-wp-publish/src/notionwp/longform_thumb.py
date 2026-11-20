"""롱폼 고도화 썸네일 — 실사 배경 위에 정해진 틀로 제목을 얹습니다.

기존 썸네일 단계(thumbnails.py)는 고객사 디자인 파일 하나로 숏폼 썸네일을 찍어 냅니다.
이 모듈은 롱폼 전용입니다. 배경 사진은 에이전트가 ChatGPT 구독(gpt-image 스킬)으로
글자 없이 만들고, 글자·로고·효과는 여기서 코드로 얹습니다. 그래서 한글이 깨지지 않고,
같은 틀이면 늘 같은 자리·크기로 나옵니다.

틀은 운영자가 고른 네 가지뿐입니다(2026-11 확정, 함부로 늘리지 않습니다):

    card        흐린 실사 배경 가운데 반투명 카드 + 분류 표시 + 두 줄 제목
    bottomleft  인물·사물 사진, 왼쪽 위 로고, 왼쪽 아래 두 줄 제목(왼쪽이 은은하게 밝아짐)
    klavuu      클라뷰 블로그 규격. 오른쪽 위 로고, 왼쪽 아래 두 줄, 아래쪽 흰 번짐
    ivory       사진 왼쪽에 아이보리가 스며드는 번짐 + 남색 두 줄 제목 + 왼쪽 아래 로고

명령:

    python -m notionwp.longform_thumb list   [--client 이름]
    python -m notionwp.longform_thumb render --style card --bg 배경.png --line1 .. --line2 .. --out 결과.png
    python -m notionwp.longform_thumb attach --page 페이지ID --file 결과.png --client 이름

제목 줄에 **굵게** 라고 쓰면 그 부분만 더 굵게 나옵니다(클라뷰 틀에서 키워드 강조용).
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from . import notion_api as napi
from .config import ConfigError, load_secrets
from .designs import load as load_design
from .designs import path_for, safe_name
from .notion_api import NotionClient
from .registry import load_clients

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "assets" / "fonts"
LOGOS = ROOT / "designs" / "logos"

#: 이 루틴이 맡는 플래너 유형이자, 설정표 '썸네일' 칸에서 찾는 값.
LONGFORM = "롱폼"
TEMPLATE_MARK = "템플릿"

STYLES = ("card", "bottomleft", "klavuu", "ivory")


# ── 대상 행 고르기 ──────────────────────────────────────────────────────────


def wants_longform(cfg) -> bool:
    """설정표 '썸네일' 칸에 롱폼이 있는 고객사만. 칸이 없거나 비면 하지 않습니다."""
    return bool(cfg.thumbnail_types) and LONGFORM in cfg.thumbnail_types


def eligible(props: dict[str, Any], cfg) -> tuple[bool, str]:
    name = cfg.notion.prop
    kind = napi.read_select(props.get(name("type")))
    if kind != LONGFORM:
        return False, f"유형이 '{kind or '미지정'}'"
    title = napi.read_text(props.get(name("title"))).strip()
    if not title:
        return False, "제목이 비어 있음"
    if TEMPLATE_MARK in title:
        return False, "제목이 아직 템플릿 이름"
    if (props.get(name("thumbnail")) or {}).get("files"):
        return False, "썸네일이 이미 있음"
    return True, ""


def list_targets(client: str = "") -> list[dict[str, str]]:
    secrets = load_secrets()
    out: list[dict[str, str]] = []
    for cfg in load_clients(secrets.notion_token, only=client, platform=None):
        if not wants_longform(cfg):
            log.info("건너뜀 [%s]: 설정표 '썸네일' 칸에 롱폼 없음", cfg.client)
            continue
        notion = NotionClient(secrets.notion_token, cfg.notion)
        for row in notion.query_database(cfg.notion.database_id):
            props = row.get("properties") or {}
            ok, _ = eligible(props, cfg)
            if not ok:
                continue
            out.append(
                {
                    "client": cfg.client,
                    "page_id": row.get("id", ""),
                    "title": napi.read_text(props.get(cfg.notion.prop("title"))).strip(),
                    "keyword": napi.read_text(props.get(cfg.notion.prop("keywords"))).strip(),
                }
            )
    return out


# ── 그리기 ─────────────────────────────────────────────────────────────────


def _inline(text: str) -> str:
    """HTML 이스케이프 후 **굵게** 만 <b> 로 바꿉니다. 줄바꿈은 \\n 또는 / 로."""
    safe = html.escape(text or "")
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe.replace("\\n", "<br>").replace("\n", "<br>")


def _font_faces() -> str:
    faces = [
        ("W", 600, "WantedSans-600.woff2"),
        ("W", 700, "WantedSans-700.woff2"),
        ("P", 500, "Pretendard-Medium.woff2"),
        ("P", 700, "Pretendard-Bold.woff2"),
        ("P", 800, "Pretendard-ExtraBold.woff2"),
    ]
    return "".join(
        f"@font-face{{font-family:{fam};font-weight:{w};src:url({(FONTS / f).as_uri()})}}"
        for fam, w, f in faces
    )


def _logo_uri(client: str) -> str:
    if not client:
        return ""
    design = load_design(client)
    if design and design.logo:
        for ext in ("png", "jpg", "jpeg", "webp", "svg"):
            path = LOGOS / f"{safe_name(client)}.{ext}"
            if path.exists():
                return path.as_uri()
    return ""


def _sample_tint(bg: Path, box: tuple[float, float, float, float]) -> tuple[int, int, int]:
    """배경의 한 영역 평균색. 번짐 색을 사진에서 뽑아야 사진과 따로 놀지 않습니다."""
    try:
        from PIL import Image

        with Image.open(bg) as im:
            im = im.convert("RGB")
            w, h = im.size
            crop = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
            r, g, b = crop.resize((1, 1)).getpixel((0, 0))
            return r, g, b
    except Exception:  # 사진을 못 읽으면 중립색
        return 245, 240, 248


def _lighten(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(c + (255 - c) * amount) for c in rgb)  # type: ignore[return-value]


NOISE = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' "
    "stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter>"
    "<rect width='100%' height='100%' filter='url(%23n)'/></svg>"
)


def canvas_for(client: str) -> tuple[int, int, tuple[float, ...]]:
    """(가로, 세로, 사이트가 잘라 보여 주는 비율들).

    고객사 디자인 파일의 width·height 를 캔버스로 쓰고, `view_crops`(가로/세로 비율 목록)에
    적힌 비율로 사이트가 가운데를 잘라 보여 준다고 봅니다. 예) 지혜로운 필라테스는
    1200x900 캔버스를 목록 카드 4:3, 글 상세 커버 2:1 로 잘라 보여 줍니다.
    디자인 파일이 없으면 1920x1080, 잘림 없음.
    """
    if client:
        path = path_for(client)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            w, h = int(raw.get("width", 1920)), int(raw.get("height", 1080))
            crops = tuple(float(r) for r in raw.get("view_crops") or ())
            return w, h, crops
    return 1920, 1080, ()


def safe_box(w: int, h: int, crops: tuple[float, ...], margin: float = 0.0) -> tuple[float, float, float, float]:
    """모든 잘림 비율에서 살아남는 가운데 영역 (x, y, 가로, 세로)."""
    sw, sh = float(w), float(h)
    for r in crops:
        if r <= 0:
            continue
        if w / h > r:  # 캔버스가 더 넓으면 좌우가 잘림
            sw = min(sw, h * r)
        else:  # 위아래가 잘림
            sh = min(sh, w / r)
    sw, sh = sw * (1 - 2 * margin), sh * (1 - 2 * margin)
    return (w - sw) / 2, (h - sh) / 2, sw, sh


def _layers(style, bg, l1, l2, logo_tag, pill, accent):
    """(배경층 css, 배경층 html, 글자층 css, 글자층 html, 글자층 원래 가로, 세로, 글꼴)."""
    bg_uri = bg.resolve().as_uri()
    bg_div = f'<div class=bg style="background-image:url({bg_uri})"></div>'

    if style == "card":
        tone = accent or "#c98b8b"
        fg_css = (
            ".logo{position:absolute;top:70px;left:120px;height:84px}"
            ".brandtext{height:auto;font-weight:700;font-size:40px;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.25)}"
            ".card{position:absolute;left:50%;top:53%;transform:translate(-50%,-50%);padding:84px 130px 96px;"
            "border-radius:44px;background:rgba(255,255,255,.66);backdrop-filter:blur(16px);"
            "box-shadow:0 30px 90px rgba(80,50,50,.20);text-align:center;white-space:nowrap;color:#2f2626}"
            f".pill{{display:inline-block;font-weight:700;font-size:46px;color:#fff;background:{tone};"
            "border-radius:999px;padding:14px 44px;margin-bottom:40px}"
            ".l1{font-weight:600;font-size:76px;letter-spacing:-2px;margin-bottom:22px}"
            ".l2{font-weight:700;font-size:132px;letter-spacing:-4px;line-height:1.1}"
        )
        pill_tag = f"<div class=pill>{html.escape(pill)}</div>" if pill else ""
        fg = f"{logo_tag}<div class=card>{pill_tag}<div class=l1>{l1}</div><div class=l2>{l2}</div></div>"
        return "", bg_div, fg_css, fg, 1920, 1080, "W"

    if style == "bottomleft":
        r, g, b = _lighten(_sample_tint(bg, (0, 0.2, 0.3, 0.9)), 0.45)
        bg_css = (
            f".fade{{position:absolute;inset:0;background:linear-gradient(90deg,rgba({r},{g},{b},.92) 0%,"
            f"rgba({r},{g},{b},.55) 40%,rgba({r},{g},{b},0) 60%)}}"
        )
        fg_css = (
            ".stage{color:#141414}"
            ".logo{position:absolute;top:70px;left:120px;height:84px}"
            ".brandtext{height:auto;font-weight:700;font-size:40px}"
            ".t{position:absolute;left:120px;bottom:150px}"
            ".l1{font-weight:600;font-size:62px;letter-spacing:-1.5px;margin-bottom:24px}"
            ".l2{font-weight:700;font-size:100px;letter-spacing:-3px;line-height:1.12}"
        )
        fg = f"{logo_tag}<div class=t><div class=l1>{l1}</div><div class=l2>{l2}</div></div>"
        return bg_css, bg_div + "<div class=fade></div>", fg_css, fg, 1920, 1080, "W"

    if style == "klavuu":
        # 클라뷰 원본(1024x594)을 픽셀 단위로 잰 값.
        bg_css = (
            ".haze{position:absolute;inset:0;background:linear-gradient(0deg,rgba(255,255,255,.88) 0%,"
            "rgba(255,255,255,.45) 22%,rgba(255,255,255,0) 46%),linear-gradient(90deg,"
            "rgba(255,255,255,.35) 0%,rgba(255,255,255,0) 45%)}"
        )
        fg_css = (
            ".stage{color:#111}"
            ".logo{position:absolute;top:30px;right:35px;width:175px}"
            ".brandtext{width:auto;font-weight:800;font-size:22px;letter-spacing:2px}"
            ".l1{position:absolute;left:70px;top:384px;font-weight:500;font-size:36px;letter-spacing:.2px;white-space:nowrap}"
            ".l2{position:absolute;left:70px;top:439px;font-weight:500;font-size:54px;letter-spacing:1px;white-space:nowrap}"
            ".l1 b,.l2 b{font-weight:800}"
        )
        fg = f"{logo_tag}<div class=l1>{l1}</div><div class=l2>{l2}</div>"
        return bg_css, bg_div + "<div class=haze></div>", fg_css, fg, 1024, 594, "P"

    # ivory
    ink = accent or "#1d2a40"
    bg_css = (
        ".haze{position:absolute;inset:0;background:linear-gradient(90deg,rgba(250,245,237,.96) 0%,"
        "rgba(250,245,237,.86) 30%,rgba(250,245,237,.35) 50%,rgba(250,245,237,0) 62%)}"
    )
    fg_css = (
        f".t{{position:absolute;left:120px;top:340px;color:{ink}}}"
        ".t .l1{color:#6b6255;font-weight:600;font-size:64px;letter-spacing:-1.5px;margin-bottom:24px}"
        ".t .l2{font-weight:700;font-size:112px;letter-spacing:-3.5px;line-height:1.1}"
        ".logo{position:absolute;left:120px;bottom:80px;height:76px}"
        f".brandtext{{height:auto;font-weight:700;font-size:38px;color:{ink}}}"
    )
    fg = f"<div class=t><div class=l1>{l1}</div><div class=l2>{l2}</div></div>{logo_tag}"
    return bg_css, bg_div + "<div class=haze></div><div class=grain></div>", fg_css, fg, 1920, 1080, "W"


def build_html(
    style: str,
    bg: Path,
    line1: str,
    line2: str,
    *,
    pill: str = "",
    client: str = "",
    brand: str = "",
    accent: str = "",
    canvas: tuple[int, int, tuple[float, ...]] | None = None,
) -> tuple[str, int, int, float]:
    """(html, 캔버스 가로, 세로, 저장 배율).

    배경·번짐은 캔버스 전체에 깔고, 글자·로고 층은 운영자가 고른 원래 배치(1920x1080,
    클라뷰는 1024x594)를 그대로 유지한 채 '모든 잘림에서 살아남는 영역' 안에 맞춰
    줄여 넣습니다. 그래서 사이트가 4:3 카드나 2:1 커버로 잘라도 글자가 잘리지 않습니다.
    """
    if style not in STYLES:
        raise ValueError(f"모르는 틀입니다: {style} (쓸 수 있는 것: {', '.join(STYLES)})")
    w, h, crops = canvas or canvas_for(client)
    sx, sy, sw, sh = safe_box(w, h, crops)
    l1, l2 = _inline(line1), _inline(line2)
    logo = _logo_uri(client)
    logo_tag = f'<img class=logo src="{logo}">' if logo else (
        f"<div class='logo brandtext'>{html.escape(brand or client)}</div>" if (brand or client) else ""
    )
    bg_css, bg_html, fg_css, fg_html, w0, h0, family = _layers(style, bg, l1, l2, logo_tag, pill, accent)
    scale = min(sw / w0, sh / h0)
    left = sx + (sw - w0 * scale) / 2
    top = sy + (sh - h0 * scale) / 2
    css = (
        _font_faces()
        + "html,body{margin:0}"
        + f".c{{position:relative;overflow:hidden;width:{w}px;height:{h}px}}"
        ".bg{position:absolute;inset:0;background-size:cover;background-position:center}"
        f".grain{{position:absolute;inset:0;background-image:url(\"{NOISE}\");opacity:.10;mix-blend-mode:overlay}}"
        f".stage{{position:absolute;left:{left:.2f}px;top:{top:.2f}px;width:{w0}px;height:{h0}px;"
        f"transform-origin:0 0;transform:scale({scale:.5f});font-family:{family}}}"
        + bg_css
        + fg_css
    )
    doc = f"<style>{css}</style><div class=c>{bg_html}<div class=stage>{fg_html}</div></div>"
    # 저장 해상도는 가로 1920 이상이 되게 키웁니다(1200 캔버스 → 1920).
    return doc, w, h, max(1.0, 1920 / w)


def render(style: str, bg: Path, line1: str, line2: str, out: Path, **kw: str) -> Path:
    from playwright.sync_api import sync_playwright

    from .thumbnail import find_chromium

    doc, w, h, scale = build_html(style, Path(bg), line1, line2, **kw)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page_file = out.with_suffix(".html")
    page_file.write_text(f"<!doctype html><meta charset=utf-8>{doc}", encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=find_chromium(), args=["--allow-file-access-from-files"]
            )
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
            page.goto(page_file.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(500)
            page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": w, "height": h})
            browser.close()
    finally:
        page_file.unlink(missing_ok=True)
    return out


def crop_previews(file: Path, client: str, out: Path) -> Path:
    """완성본을 사이트가 자르는 비율대로 잘라 나란히 붙인 확인용 그림."""
    from PIL import Image, ImageDraw

    _, _, crops = canvas_for(client)
    with Image.open(file) as im:
        im = im.convert("RGB")
        W, H = im.size
        shots = [("full", im.copy())]
        for r in crops:
            if W / H > r:
                cw, ch = int(H * r), H
            else:
                cw, ch = W, int(W / r)
            x, y = (W - cw) // 2, (H - ch) // 2
            shots.append((f"{r:.2f}:1", im.crop((x, y, x + cw, y + ch))))
    tile_h = 360
    tiles = [(label, s.resize((int(s.width * tile_h / s.height), tile_h))) for label, s in shots]
    sheet = Image.new("RGB", (sum(t.width for _, t in tiles) + 20 * (len(tiles) + 1), tile_h + 60), "white")
    x = 20
    draw = ImageDraw.Draw(sheet)
    for label, t in tiles:
        sheet.paste(t, (x, 40))
        draw.text((x, 12), label, fill=(60, 60, 60))
        x += t.width + 20
    out = Path(out)
    sheet.save(out)
    return out


# ── 붙이기 ─────────────────────────────────────────────────────────────────


def attach(page_id: str, file: Path, client: str) -> None:
    secrets = load_secrets()
    configs = load_clients(secrets.notion_token, only=client, platform=None)
    cfg = next((c for c in configs if c.client.strip() == client.strip()), None) or (
        configs[0] if len(configs) == 1 else None
    )
    if cfg is None:
        raise ConfigError(f"설정표에서 '{client}' 고객사를 찾지 못했습니다.")
    notion = NotionClient(secrets.notion_token, cfg.notion)
    # 붙이기 직전에 다시 확인합니다. 그사이 사람이 썸네일을 올렸으면 덮어쓰지 않습니다.
    page = notion._request("GET", f"/pages/{page_id}")
    ok, reason = eligible(page.get("properties") or {}, cfg)
    if not ok:
        raise ConfigError(f"붙이지 않습니다: {reason}")
    data = Path(file).read_bytes()
    filename = Path(file).name
    upload_id = notion.upload_file(data, filename, "image/png")
    notion.update_page(page_id, {cfg.notion.prop("thumbnail"): napi.write_files([(upload_id, filename)])})


# ── 명령줄 ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(prog="python -m notionwp.longform_thumb", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="썸네일이 필요한 롱폼 행을 JSON 으로 출력")
    p_list.add_argument("--client", default="")

    p_render = sub.add_parser("render", help="배경 사진 위에 틀로 글자를 얹어 PNG 로 저장")
    p_render.add_argument("--style", required=True, choices=STYLES)
    p_render.add_argument("--bg", required=True)
    p_render.add_argument("--line1", required=True, help="작은 윗줄")
    p_render.add_argument("--line2", required=True, help="큰 제목. 두 줄이면 \\n")
    p_render.add_argument("--pill", default="", help="card 틀의 분류 표시")
    p_render.add_argument("--client", default="", help="로고를 가져올 고객사")
    p_render.add_argument("--brand", default="", help="로고 파일이 없을 때 대신 쓸 이름")
    p_render.add_argument("--accent", default="", help="card 분류 표시 색 / ivory 글자색 (#RRGGBB)")
    p_render.add_argument("--out", required=True)

    p_crops = sub.add_parser("crops", help="완성본을 사이트가 자르는 비율대로 잘라 본 확인용 그림")
    p_crops.add_argument("--file", required=True)
    p_crops.add_argument("--client", required=True)
    p_crops.add_argument("--out", required=True)

    p_attach = sub.add_parser("attach", help="만든 PNG 를 그 행의 썸네일 칸에 붙임")
    p_attach.add_argument("--page", required=True)
    p_attach.add_argument("--file", required=True)
    p_attach.add_argument("--client", required=True)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            print(json.dumps(list_targets(args.client), ensure_ascii=False, indent=2))
        elif args.cmd == "render":
            out = render(
                args.style, Path(args.bg), args.line1, args.line2, Path(args.out),
                pill=args.pill, client=args.client, brand=args.brand, accent=args.accent,
            )
            print(out)
        elif args.cmd == "crops":
            print(crop_previews(Path(args.file), args.client, Path(args.out)))
        else:
            attach(args.page, Path(args.file), args.client)
            print("붙였습니다")
    except (ConfigError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
