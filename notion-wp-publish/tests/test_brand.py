# -*- coding: utf-8 -*-
"""고객사 홈페이지에서 브랜드 정보를 알아내기."""

from __future__ import annotations

from notionwp.brand import (
    FALLBACK_COLOR,
    domain_of,
    inspect,
    is_brandish,
    to_hex,
    to_rgb,
)

PAGE = """
<html><head>
<meta name="theme-color" content="#0B3D80">
<meta property="og:site_name" content="Clear Seoul Eye Clinic">
<link rel="icon" href="/favicon.png">
</head><body>
<img class="site-logo" src="/img/logo.svg" alt="클리어서울안과">
</body></html>
"""


def fetcher(pages: dict[str, tuple[str, bytes, str]]):
    def fetch(url: str):
        if url not in pages:
            raise RuntimeError(f"404 {url}")
        return pages[url]

    return fetch


# ---------------------------------------------------------------- 색 파싱

def test_reads_hex_and_rgb():
    assert to_rgb("#0B3D80") == (11, 61, 128)
    assert to_rgb("#abc") == (170, 187, 204)
    assert to_rgb("rgb(11, 61, 128)") == (11, 61, 128)
    assert to_rgb("자홍색") is None


def test_greys_and_extremes_are_not_brand_colours():
    """흰·검·회색은 배경과 글자 색이지 브랜드 컬러가 아닙니다."""
    assert not is_brandish((255, 255, 255))
    assert not is_brandish((0, 0, 0))
    assert not is_brandish((136, 136, 136))
    assert is_brandish((11, 61, 128))


def test_hex_round_trip_is_uppercase():
    assert to_hex((11, 61, 128)) == "#0B3D80"


# ---------------------------------------------------------------- 도메인

def test_domain_strips_scheme_and_www():
    assert domain_of("https://www.clearseouleye.com/about") == "clearseouleye.com"
    assert domain_of("blog.cleartone.co.kr") == "blog.cleartone.co.kr"


# ---------------------------------------------------------------- 전체

def test_theme_colour_wins():
    fetch = fetcher({
        "https://clearseouleye.com": (PAGE, b"", "text/html"),
        "https://clearseouleye.com/img/logo.svg": ("", b"<svg/>", "image/svg+xml"),
    })
    brand = inspect("https://clearseouleye.com", "클리어서울안과", fetch)
    assert brand.color == "#0B3D80"
    assert brand.domain == "clearseouleye.com"
    assert brand.name_en == "CLEAR SEOUL EYE CLINIC"
    assert brand.has_logo


def test_a_missing_logo_is_not_a_failure():
    """로고를 못 찾아도 워드마크로 대신하면 되므로 그냥 진행합니다."""
    fetch = fetcher({"https://x.kr": (PAGE, b"", "text/html")})
    brand = inspect("https://x.kr", "어떤의원", fetch)
    assert not brand.has_logo
    assert brand.color == "#0B3D80"


def test_unreachable_site_falls_back_to_defaults():
    def fetch(url: str):
        raise RuntimeError("연결할 수 없습니다")

    brand = inspect("https://down.example.com", "어떤의원", fetch)
    assert brand.color == FALLBACK_COLOR
    assert brand.name == "어떤의원"
    assert not brand.has_logo


def test_most_common_colour_when_no_theme_colour():
    html = """<html><body><style>
      .a{color:#1E5AA8} .b{border:1px solid #1E5AA8} .c{background:#FFFFFF}
      .d{background:#1E5AA8} .e{color:#333333}
    </style></body></html>"""
    fetch = fetcher({"https://y.kr": (html, b"", "text/html")})
    assert inspect("https://y.kr", "어떤의원", fetch).color == "#1E5AA8"


def test_oversized_logo_is_skipped():
    fetch = fetcher({
        "https://z.kr": (PAGE, b"", "text/html"),
        "https://z.kr/img/logo.svg": ("", b"x" * 4_000_000, "image/svg+xml"),
        "https://z.kr/favicon.png": ("", b"\x89PNG", "image/png"),
    })
    brand = inspect("https://z.kr", "어떤의원", fetch)
    assert brand.logo == b"\x89PNG"
