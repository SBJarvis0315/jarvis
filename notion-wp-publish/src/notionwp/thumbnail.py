"""썸네일 자동 생성.

고객사 홈페이지에서 알아낸 브랜드 컬러 하나로 한 벌의 색을 만들고, 제목을
얹어 이미지를 찍어냅니다. 사람이 정해줄 것이 없도록 하는 게 목표입니다 —
색도 로고도 `brand.inspect` 가 알아서 찾고, 못 찾으면 못 찾은 대로 갑니다.

골격이 둘 있습니다. 고객사 디자인 파일의 `skeleton` 이 하나를 고릅니다.

    band (1200x630)                    minimal (1920x1080)
    ┌──────────────────────────┐       ┌──────────────────────────┐
    │ [ 키워드 뱃지 ]           │       │  로고                     │
    │  메인 타이틀              │       │                          │
    │                          │       │  메인 타이틀              │
    │  서브 타이틀              │       │                          │
    │ ──────────────────────── │       │  서브 타이틀              │
    │  고객사명        도메인    │       │                          │
    └──────────────────────────┘       └──────────────────────────┘
    진한 바탕·정보 밀도 높음            흰 바탕·여백 위주, 로고가 중심

제목은 팀이 '메인 키워드 | 부연' 형태로 쓰고 있으므로 그 경계에서 갈라
앞토막을 큰 글씨로 씁니다(`split_title`).

렌더링은 Chromium 헤드리스로 합니다. 글자가 길어지면 상자에 들어올 때까지
크기를 줄여야 하는데, 실제로 조판해 보기 전에는 몇 줄이 될지 알 수 없어서
브라우저의 레이아웃 엔진을 그대로 빌려 쓰는 편이 정확합니다.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .brand import Brand, luminance, to_hex, to_rgb

log = logging.getLogger(__name__)

#: 세로바 계열만 제목 경계로 봅니다. 'ㅣ'(한글 자모)도 실수로 자주 섞여 들어옵니다.
#: '·' 는 "원리·통증·유지기간" 처럼 서브 타이틀 *안에서* 나열 기호로 쓰이므로 제외합니다.
BARS = "|｜ㅣ"

#: 물음표로 끝나는 앞토막도 하나의 덩어리입니다. 부호는 앞토막에 남깁니다.
ENDERS = "?!？！"

#: 기본 규격은 OG 이미지 크기입니다. 블로그 카드·검색 결과·SNS 미리보기가 전부 이 비율입니다.
WIDTH = 1200
HEIGHT = 630

#: 이 밑으로는 줄이지 않습니다. 더 줄이느니 잘리는 편이 눈에 띄어서 낫습니다.
#: 1200px 폭 기준. 다른 폭으로 그릴 때는 비례해서 늘립니다.
MIN_MAIN_SIZE = 30
MAX_MAIN_SIZE = 54

#: `--window-size` 는 바깥 창 크기라서 실제 뷰포트는 그보다 작습니다(1080 → 993).
#: 넉넉히 잡아 찍고 정확한 크기로 잘라냅니다. 줄어든 양은 빌드마다 다를 수 있습니다.
VIEWPORT_SLACK = 240


class ThumbnailError(RuntimeError):
    pass


def mix(a: str, b: str, t: float) -> str:
    """색 a 를 b 쪽으로 t 만큼 섞습니다. t=0 이면 a, t=1 이면 b."""
    ra, rb = to_rgb(a), to_rgb(b)
    if not ra or not rb:
        return a
    return to_hex(tuple(round(x + (y - x) * t) for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def to_hsl(color: str) -> tuple[float, float, float]:
    rgb = to_rgb(color) or (0, 0, 0)
    r, g, b = (c / 255 for c in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    l = (hi + lo) / 2
    if hi == lo:
        return 0.0, 0.0, l
    d = hi - lo
    s = d / (2 - hi - lo) if l > 0.5 else d / (hi + lo)
    if hi == r:
        h = ((g - b) / d) % 6
    elif hi == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60, s, l


def from_hsl(h: float, s: float, l: float) -> str:
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    seg = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)]
    r, g, b = seg[int(h // 60) % 6]
    return to_hex((round((r + m) * 255), round((g + m) * 255), round((b + m) * 255)))


def vivid(color: str) -> str:
    """같은 색상(hue)의 선명하고 밝은 버전. 액센트 바와 뱃지 글씨에 씁니다."""
    h, s, _ = to_hsl(color)
    return from_hsl(h, max(s, 0.72), 0.60)


def readable_on(fg: str, bg: str, gap: float = 0.30) -> str:
    """`bg` 위에서 읽히도록 `fg` 를 흰색 쪽으로 밀어 올립니다.

    브랜드 컬러가 이미 밝으면 vivid() 결과가 뱃지 배경과 너무 가까워져 글씨가
    묻힙니다. 밝기 차가 벌어질 때까지 흰색을 섞습니다.
    """
    back = to_rgb(bg)
    if not back:
        return fg
    target = luminance(back)
    for step in range(11):
        candidate = mix(fg, "#FFFFFF", step / 10)
        rgb = to_rgb(candidate)
        if rgb and abs(luminance(rgb) - target) >= gap:
            return candidate
    return "#FFFFFF"


@dataclass
class Palette:
    """브랜드 컬러 하나에서 파생된 한 벌의 색."""

    background: str
    accent: str
    title: str
    sub: str
    pill_bg: str
    pill_fg: str
    brand: str
    muted: str
    rule: str
    ornament: str

    @classmethod
    def derive(cls, color: str) -> Palette:
        """어두운 브랜드 컬러는 배경으로 깔고, 밝은 색은 옅게 깔고 글씨를 진하게."""
        rgb = to_rgb(color) or (43, 79, 199)

        if luminance(rgb) < 0.55:
            # 진한 변형 — 브랜드 컬러가 그대로 배경이 됩니다. 레퍼런스가 이 쪽입니다.
            return cls(
                background=color,
                accent=vivid(color),
                title="#FFFFFF",
                sub=mix(color, "#FFFFFF", 0.66),
                pill_bg=mix(color, "#FFFFFF", 0.12),
                pill_fg=readable_on(vivid(color), mix(color, "#FFFFFF", 0.12)),
                brand="#FFFFFF",
                muted=mix(color, "#FFFFFF", 0.50),
                rule=mix(color, "#FFFFFF", 0.20),
                ornament=mix(color, "#FFFFFF", 0.09),
            )

        # 밝은 변형 — 배경은 아주 옅게 깔고 글씨를 진하게 씁니다.
        deep = mix(color, "#000000", 0.55)
        return cls(
            background=mix(color, "#FFFFFF", 0.93),
            accent=vivid(color),
            title=deep,
            sub=mix(deep, "#FFFFFF", 0.28),
            pill_bg=mix(color, "#FFFFFF", 0.80),
            pill_fg=deep,
            brand=deep,
            muted=mix(deep, "#FFFFFF", 0.52),
            rule=mix(color, "#FFFFFF", 0.72),
            ornament=mix(color, "#FFFFFF", 0.88),
        )


#: 저장소에 담아 둔 폰트. 실행할 때 인터넷에서 받아오지 않습니다.
FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def _font_format(blob: bytes) -> tuple[str, str]:
    """폰트 바이트에서 형식을 알아냅니다. (mime, CSS format 이름)"""
    if blob[:4] == b"wOF2":
        return "font/woff2", "woff2"
    if blob[:4] == b"wOFF":
        return "font/woff", "woff"
    return "font/ttf", "truetype"


@dataclass
class Fonts:
    """조판에 쓸 폰트. 라틴과 한글이 다른 파일이라 둘 다 받습니다."""

    latin_bold: bytes = b""
    latin_semibold: bytes = b""
    hangul_bold: bytes = b""
    hangul_semibold: bytes = b""

    @classmethod
    def bundled(cls, latin: str = "NataSans", hangul: str = "NotoSansKR") -> Fonts:
        """저장소에 담아 둔 폰트를 읽습니다. 고객사마다 다른 서체를 고를 수 있습니다."""

        def read(family: str, weight: int) -> bytes:
            for ext in ("woff2", "woff", "ttf"):
                path = FONT_DIR / f"{family}-{weight}.{ext}"
                if path.exists():
                    return path.read_bytes()
            raise ThumbnailError(f"폰트를 찾지 못했습니다: {FONT_DIR}/{family}-{weight}")

        return cls(
            latin_bold=read(latin, 700),
            latin_semibold=read(latin, 600),
            hangul_bold=read(hangul, 700),
            hangul_semibold=read(hangul, 600),
        )

    def faces(self) -> str:
        pairs = [
            ("Latin", 700, self.latin_bold),
            ("Latin", 600, self.latin_semibold),
            ("Hangul", 700, self.hangul_bold),
            ("Hangul", 600, self.hangul_semibold),
        ]
        out = []
        for fam, weight, blob in pairs:
            if not blob:
                continue
            mime, fmt = _font_format(blob)
            out.append(
                "@font-face{font-family:'%s';font-weight:%d;"
                "src:url(data:%s;base64,%s) format('%s');}"
                % (fam, weight, mime, base64.b64encode(blob).decode(), fmt)
            )
        return "".join(out)


def split_title(title: str, client: str = "") -> tuple[str, str]:
    """제목을 메인/서브로 가릅니다.

        기미 레이저 가격 | 강남 기준 비용 정리  →  ('기미 레이저 가격', '강남 기준 비용 정리')
        오타모반이란? 색소침착과 차이           →  ('오타모반이란?', '색소침착과 차이')
        클리어톤의원은 어떤 곳인가요?            →  ('클리어톤의원은 어떤 곳인가요?', '클리어톤의원')

    메인 키워드가 앞에 오도록 팀이 제목을 쓰고 있으므로, 앞토막을 그대로 큰 글씨로
    씁니다. 구분 기호가 없으면 제목 전체가 메인이고 서브는 고객사명으로 채웁니다.
    """
    text = " ".join((title or "").split())
    if not text:
        return "", ""

    bar = re.search(r"\s*[" + re.escape(BARS) + r"]\s*", text)
    if bar and bar.start() > 0:
        return text[: bar.start()].strip(), text[bar.end() :].strip()

    ender = re.search(r"[" + re.escape(ENDERS) + r"]\s+", text)
    if ender:
        return text[: ender.end()].strip(), text[ender.end() :].strip()

    return text, client.strip()


def badge_text(keywords: str) -> str:
    """뱃지에 넣을 말. 키워드 목록의 첫 번째가 메인 키워드입니다."""
    first = (keywords or "").split(",")[0].strip()
    return first if len(first) <= 14 else ""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_html(
    main: str,
    sub: str,
    brand: Brand,
    fonts: Fonts,
    *,
    badge: str = "",
    width: int = WIDTH,
    height: int = HEIGHT,
    palette: Palette | None = None,
    skeleton: str = "band",
) -> str:
    """골격을 골라 조판합니다. 골격은 고객사 디자인 파일이 정합니다."""
    builder = SKELETONS.get(skeleton)
    if builder is None:
        raise ThumbnailError(
            f"모르는 골격입니다: {skeleton} (쓸 수 있는 것: {', '.join(SKELETONS)})"
        )
    return builder(main, sub, brand, fonts, badge, width, height, palette)


def _band_html(
    main: str,
    sub: str,
    brand: Brand,
    fonts: Fonts,
    badge: str,
    width: int,
    height: int,
    palette: Palette | None,
) -> str:
    """진한 바탕에 뱃지·하단 브랜드 바가 있는 골격. 1200x630 기준."""
    # 고객사 전용 디자인이 있으면 그 팔레트를 그대로 씁니다. 없을 때만 색을 파생합니다.
    p = palette or Palette.derive(brand.color)
    u = width / WIDTH  # 1200px 기준으로 잡은 치수를 요청한 폭에 맞춰 늘립니다.

    def px(v: float) -> str:
        return f"{v * u:.2f}px"

    if brand.has_logo:
        src = f"data:{brand.logo_mime};base64,{base64.b64encode(brand.logo).decode()}"
        mark = f'<img class="logo" src="{src}">'
    else:
        # 로고를 못 찾아도 브랜드가 빠지면 안 됩니다. 이름을 워드마크로 세웁니다.
        mark = f'<div class="wordmark">{_escape(brand.name)}</div>'
        if brand.name_en:
            mark += f'<div class="worden">{_escape(brand.name_en)}</div>'

    return f"""<!doctype html><meta charset="utf-8"><style>
{fonts.faces()}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Latin','Hangul',sans-serif}}
.frame{{position:relative;width:{width}px;height:{height}px;background:{p.background};
  overflow:hidden;display:flex;flex-direction:column}}
.accent{{flex:none;height:{px(6)};background:{p.accent}}}
.orn{{position:absolute;border-radius:50%;border:{px(1.5)} solid {p.ornament};
  width:{px(620)};height:{px(620)};right:{px(-150)};top:{px(160)}}}
.orn2{{position:absolute;border-radius:50%;background:{p.ornament};
  width:{px(430)};height:{px(430)};right:{px(-120)};top:{px(255)}}}
.body{{position:relative;flex:1;padding:{px(44)} {px(56)} 0}}
.stack{{display:flex;flex-direction:column;align-items:flex-start}}
.pill{{background:{p.pill_bg};color:{p.pill_fg};font-size:{px(15)};font-weight:700;
  padding:{px(9)} {px(20)};border-radius:999px;margin-bottom:{px(26)};
  letter-spacing:-0.01em}}
.main{{color:{p.title};font-weight:700;font-size:{px(MAX_MAIN_SIZE)};line-height:1.22;
  letter-spacing:-0.03em;word-break:keep-all}}
.sub{{color:{p.sub};font-weight:600;font-size:{px(22)};line-height:1.45;
  margin-top:{px(150)};word-break:keep-all}}
.foot{{position:relative;flex:none;padding:0 {px(56)} {px(34)}}}
.rule{{height:1px;width:72%;background:{p.rule};margin-bottom:{px(24)}}}
.row{{display:flex;align-items:flex-end;justify-content:space-between}}
.wordmark{{color:{p.brand};font-size:{px(19)};font-weight:700;letter-spacing:-0.02em}}
.worden{{color:{p.muted};font-size:{px(10)};font-weight:600;letter-spacing:0.16em;
  margin-top:{px(4)}}}
.logo{{max-width:{px(260)};max-height:{px(46)};object-fit:contain;object-position:left bottom}}
.domain{{color:{p.muted};font-size:{px(15)};font-weight:600;letter-spacing:0.04em}}
</style>
<div class="frame">
  <div class="accent"></div>
  <div class="orn"></div><div class="orn2"></div>
  <div class="body"><div class="stack">
    {f'<div class="pill">{_escape(badge)}</div>' if badge else ''}
    <div class="main">{_escape(main)}</div>
    {f'<div class="sub">{_escape(sub)}</div>' if sub else ''}
  </div></div>
  <div class="foot">
    <div class="rule"></div>
    <div class="row"><div>{mark}</div>
      <div class="domain">{_escape(brand.domain)}</div></div>
  </div>
</div>
<script>
// 제목이 길면 서브 타이틀이 아래 구분선을 넘지 않을 때까지 글자를 줄입니다.
// 재는 대상은 '.body'가 아니라 그 안의 '.stack' 입니다 — .body 는 flex:1 이라
// 내용이 얼마든 scrollHeight 가 clientHeight 와 같게 나와서 기준이 되지 못합니다.
(function () {{
  const body = document.querySelector('.body');
  const stack = document.querySelector('.stack');
  const main = document.querySelector('.main');
  // clientHeight 는 위쪽 패딩을 포함합니다. 아래로 숨 쉴 틈을 조금 남깁니다.
  const room = body.clientHeight - {44 * 1} * {u:.4f} - {16 * 1} * {u:.4f};
  let size = {MAX_MAIN_SIZE} * {u:.4f};
  const floor = {MIN_MAIN_SIZE} * {u:.4f};
  while (stack.offsetHeight > room && size > floor) {{
    size -= 1;
    main.style.fontSize = size + 'px';
  }}
}})();
</script>"""


#: 여백형 골격의 기준 폭. 16:9 로 그립니다.
MINIMAL_WIDTH = 1920
MINIMAL_HEIGHT = 1080
MINIMAL_MIN_MAIN = 68
MINIMAL_MAX_MAIN = 130


def _minimal_html(
    main: str,
    sub: str,
    brand: Brand,
    fonts: Fonts,
    badge: str,
    width: int,
    height: int,
    palette: Palette | None,
) -> str:
    """흰 바탕에 로고를 위에 크게 놓고 여백으로 버티는 골격. 1920x1080 기준.

    뱃지·하단 바·장식이 없습니다. 로고와 제목 두 줄만으로 서는 구성이라
    브랜드 로고가 또렷한 고객사에 맞습니다. `badge` 는 쓰지 않습니다.
    """
    p = palette or Palette.derive(brand.color)
    u = width / MINIMAL_WIDTH

    def px(v: float) -> str:
        return f"{v * u:.2f}px"

    if brand.has_logo:
        src = f"data:{brand.logo_mime};base64,{base64.b64encode(brand.logo).decode()}"
        mark = f'<img class="logo" src="{src}">'
    else:
        # 로고가 이 골격의 중심이라, 없으면 이름을 그 자리에 크게 세웁니다.
        mark = f'<div class="wordmark">{_escape(brand.name)}</div>'
        if brand.name_en:
            mark += f'<div class="worden">{_escape(brand.name_en)}</div>'

    return f"""<!doctype html><meta charset="utf-8"><style>
{fonts.faces()}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Latin','Hangul',sans-serif}}
.frame{{width:{width}px;height:{height}px;background:{p.background};
  overflow:hidden;padding:{px(160)} {px(175)} {px(120)}}}
.logo{{max-width:{px(600)};max-height:{px(155)};object-fit:contain;
  object-position:left top;display:block}}
.wordmark{{color:{p.title};font-size:{px(76)};font-weight:700;letter-spacing:{px(8)}}}
.worden{{color:{p.sub};font-size:{px(26)};font-weight:600;letter-spacing:{px(9)};
  margin-top:{px(14)}}}
.main{{color:{p.title};font-weight:700;font-size:{px(MINIMAL_MAX_MAIN)};
  line-height:1.24;letter-spacing:-0.03em;word-break:keep-all;margin-top:{px(180)}}}
.sub{{color:{p.sub};font-weight:700;font-size:{px(40)};line-height:1.45;
  word-break:keep-all;margin-top:{px(110)}}}
</style>
<div class="frame">
  <div class="head">{mark}</div>
  <div class="main">{_escape(main)}</div>
  {f'<div class="sub">{_escape(sub)}</div>' if sub else ''}
</div>
<script>
// 제목이 길어지면 프레임 밖으로 밀려나므로, 다 들어올 때까지 줄입니다.
(function () {{
  const frame = document.querySelector('.frame');
  const main = document.querySelector('.main');
  let size = {MINIMAL_MAX_MAIN} * {u:.5f};
  const floor = {MINIMAL_MIN_MAIN} * {u:.5f};
  const fits = () => frame.scrollHeight <= frame.clientHeight;
  while (!fits() && size > floor) {{
    size -= 2;
    main.style.fontSize = size + 'px';
  }}
}})();
</script>"""


#: 쓸 수 있는 골격. 고객사 디자인 파일의 `skeleton` 값이 여기서 하나를 고릅니다.
SKELETONS = {
    "band": _band_html,
    "minimal": _minimal_html,
}


def find_chromium() -> str:
    """헤드리스 브라우저를 찾습니다. 환경마다 놓인 자리가 달라 순서대로 뒤집니다."""
    if os.environ.get("CHROMIUM_PATH"):
        return os.environ["CHROMIUM_PATH"]

    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if root.is_dir():
        for pattern in (
            "chromium-*/chrome-linux/chrome",
            "chromium_headless_shell-*/chrome-linux/headless_shell",
        ):
            found = sorted(root.glob(pattern))
            if found:
                return str(found[-1])

    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        path = shutil.which(name)
        if path:
            return path

    raise ThumbnailError(
        "썸네일을 그릴 브라우저를 찾지 못했습니다. "
        "CHROMIUM_PATH 환경변수로 실행 파일 경로를 지정해 주세요."
    )


def render(
    main: str,
    sub: str,
    brand: Brand,
    fonts: Fonts,
    *,
    badge: str = "",
    width: int = WIDTH,
    height: int = HEIGHT,
    scale: float = 1.0,
    timeout: int = 60,
    palette: Palette | None = None,
    skeleton: str = "band",
) -> bytes:
    """썸네일 한 장을 PNG 바이트로 돌려줍니다."""
    if not main.strip():
        raise ThumbnailError("썸네일에 넣을 제목이 없습니다.")

    html = build_html(main, sub, brand, fonts, badge=badge, width=width,
                      height=height, palette=palette, skeleton=skeleton)

    with tempfile.TemporaryDirectory() as tmp:
        page, shot = Path(tmp, "page.html"), Path(tmp, "out.png")
        page.write_text(html, encoding="utf-8")

        proc = subprocess.run(
            [
                find_chromium(), "--headless", "--no-sandbox", "--disable-gpu",
                "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                f"--window-size={width},{height + VIEWPORT_SLACK}",
                f"--screenshot={shot}", "--virtual-time-budget=5000", str(page),
            ],
            capture_output=True,
            timeout=timeout,
        )

        if not shot.exists() or shot.stat().st_size == 0:
            raise ThumbnailError(
                f"썸네일 렌더링에 실패했습니다: {proc.stderr.decode('utf-8', 'replace')[:300]}"
            )
        return _crop(shot.read_bytes(), width, height)


def _crop(png: bytes, width: int, height: int) -> bytes:
    """여유를 두고 찍은 그림에서 프레임만 잘라냅니다.

    크로미움이 요청한 배율을 그대로 쓰지 않는 경우가 있어(0.45 를 넘겨도 0.5 로
    찍힙니다), 실제 폭에서 배율을 되짚어 높이를 계산합니다.
    """
    from PIL import Image  # 지연 import — 자르기가 필요할 때만.

    with Image.open(io.BytesIO(png)) as im:
        actual = im.width / width
        box = (0, 0, im.width, min(im.height, round(height * actual)))
        out = io.BytesIO()
        im.crop(box).save(out, format="PNG", optimize=True)
        return out.getvalue()
