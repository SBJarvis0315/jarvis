"""고객사 브랜드 정보를 스스로 알아냅니다.

썸네일을 그리려면 브랜드 컬러와 이름이 필요한데, 사람이 매번 설정표에 적어 넣게
하면 새 고객사를 붙일 때마다 일이 생깁니다. 고객사 홈페이지를 한 번 읽어
알아내는 편이 낫습니다.

색은 하나만 찾으면 됩니다. 나머지(배경·글자·뱃지·하단 바)는 전부 그 하나에서
파생됩니다 — `thumbnail.Palette` 참고.

찾는 순서는 확실한 것부터입니다:

    1. <meta name="theme-color">     사이트가 스스로 밝힌 대표색
    2. 로고 이미지의 대표색           브랜드가 실제로 쓰는 색
    3. CSS 안에서 가장 자주 쓰인 색    본문 링크·버튼 색
    4. 못 찾으면 기본 남색

로고도 마찬가지로 못 찾으면 없는 채로 갑니다. 워드마크로 대신하면 되므로
로고를 못 찾은 것이 실패는 아닙니다.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

FETCH_TIMEOUT = 20

#: 아무것도 못 찾았을 때. 의료 쪽에서 무난한 남색입니다.
FALLBACK_COLOR = "#2B4FC7"

#: 배경·글자로 쓰이는 무채색은 브랜드 컬러가 아닙니다. 채도와 명도로 걸러냅니다.
MIN_SATURATION = 0.25
LUMINANCE_RANGE = (0.12, 0.72)

_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
_RGB = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


@dataclass
class Brand:
    """썸네일에 필요한 고객사 정보."""

    name: str = ""
    #: 국문명 아래 작게 들어가는 영문명. 없으면 그 줄을 비웁니다.
    name_en: str = ""
    #: 우하단에 들어가는 도메인. www 는 뗍니다.
    domain: str = ""
    color: str = FALLBACK_COLOR
    logo: bytes = b""
    logo_mime: str = "image/png"

    @property
    def has_logo(self) -> bool:
        return bool(self.logo)


# ---------------------------------------------------------------- 색 유틸

def to_rgb(value: str) -> tuple[int, int, int] | None:
    """'#abc' · '#aabbcc' · 'rgb(1,2,3)' 을 (r, g, b) 로."""
    text = (value or "").strip()

    m = _HEX.fullmatch(text) or _HEX.match(text)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    m = _RGB.match(text)
    if m:
        vals = tuple(min(255, int(g)) for g in m.groups())
        return vals[0], vals[1], vals[2]

    return None


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(c))) for c in rgb)


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturation(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    if hi == 0:
        return 0.0
    return (hi - lo) / hi


def is_brandish(rgb: tuple[int, int, int]) -> bool:
    """브랜드 컬러로 쓸 만한 색인지. 흰·검·회색과 너무 밝거나 어두운 색을 뺍니다."""
    lo, hi = LUMINANCE_RANGE
    return saturation(rgb) >= MIN_SATURATION and lo <= luminance(rgb) <= hi


# ---------------------------------------------------------------- 페이지 읽기

def _meta_color(html: str) -> str:
    for pattern in (
        r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']theme-color["\']',
    ):
        m = re.search(pattern, html, re.I)
        if m:
            rgb = to_rgb(m.group(1))
            if rgb and is_brandish(rgb):
                return to_hex(rgb)
    return ""


def _common_color(html: str) -> str:
    """문서에 등장하는 색 중 브랜드다운 것 가운데 가장 흔한 것."""
    found: Counter[str] = Counter()
    for m in _HEX.finditer(html):
        rgb = to_rgb(m.group(0))
        if rgb and is_brandish(rgb):
            found[to_hex(rgb)] += 1
    for m in _RGB.finditer(html):
        rgb = to_rgb(m.group(0))
        if rgb and is_brandish(rgb):
            found[to_hex(rgb)] += 1

    return found.most_common(1)[0][0] if found else ""


def _logo_urls(html: str, base: str) -> list[str]:
    """로고일 법한 주소를, 그럴듯한 순서로."""
    out: list[str] = []

    # ① 클래스·파일명에 logo 가 들어간 <img>
    for m in re.finditer(r"<img[^>]+>", html, re.I):
        tag = m.group(0)
        if "logo" not in tag.lower():
            continue
        src = re.search(r'src=["\']([^"\']+)', tag)
        if src:
            out.append(src.group(1))

    # ② og:image — 로고가 아닐 때도 많아 뒤에 둡니다.
    for pattern in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]+href=["\']([^"\']+)',
    ):
        for m in re.finditer(pattern, html, re.I):
            out.append(m.group(1))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in out:
        url = urljoin(base, raw.strip())
        if url not in seen and url.startswith("http"):
            seen.add(url)
            urls.append(url)
    return urls


def _english_name(html: str) -> str:
    """og:site_name 등에서 영문 표기를 줍습니다. 없으면 빈 문자열."""
    for pattern in (
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
        r"<title[^>]*>([^<]+)</title>",
    ):
        m = re.search(pattern, html, re.I)
        if not m:
            continue
        # 라틴 문자와 공백만 남는 조각이어야 영문명입니다.
        for piece in re.split(r"[|·\-–—:]", m.group(1)):
            piece = piece.strip()
            if len(piece) >= 4 and re.fullmatch(r"[A-Za-z][A-Za-z .&']+", piece):
                return piece.upper()
    return ""


def domain_of(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return re.sub(r"^www\.", "", host).split(":")[0]


def inspect(url: str, name: str, fetch: Any) -> Brand:
    """고객사 홈페이지를 읽어 브랜드 정보를 채웁니다.

    `fetch(url) -> (본문, 바이트, content-type)` 를 넘겨받습니다. 망을 직접 만지지
    않게 해두어야 테스트에서 갈아 끼울 수 있습니다.

    무엇 하나 못 찾아도 예외를 던지지 않습니다. 못 찾은 자리는 기본값으로 두고,
    썸네일은 그대로 만들어집니다.
    """
    brand = Brand(name=name, domain=domain_of(url))

    try:
        html, _, _ = fetch(url)
    except Exception as exc:
        log.warning("'%s' 홈페이지를 읽지 못했습니다: %s", url, exc)
        return brand

    brand.color = _meta_color(html) or _common_color(html) or FALLBACK_COLOR
    brand.name_en = _english_name(html)

    for candidate in _logo_urls(html, url)[:4]:
        try:
            _, blob, ctype = fetch(candidate)
        except Exception:
            continue
        # SVG 는 크로미움이 그대로 그리므로 함께 받습니다.
        if blob and ctype.startswith("image/") and len(blob) < 3_000_000:
            brand.logo, brand.logo_mime = blob, ctype.split(";")[0]
            break
    else:
        log.info("'%s' 로고를 찾지 못했습니다. 워드마크로 대신합니다.", name)

    return brand
