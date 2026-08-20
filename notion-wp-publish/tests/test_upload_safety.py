"""업로드 안전장치 — 큰 사진 축소와, 응답을 못 받았을 때의 중복 방지.

실제로 겪은 사고: 노션 원본이 10MB대라 워드프레스가 60초 안에 응답하지 못했고,
클라이언트가 그대로 재시도하는 사이 같은 사진이 미디어 라이브러리에 7장 쌓였습니다.
서버에서는 매번 업로드가 성공하고 있었고, 응답만 못 받은 상황이었습니다.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp.images import UPLOAD_MAX_EDGE, web_ready
from notionwp.wordpress import WordPressClient, WordPressError
from test_gate_schema import CONFIG

PIL = pytest.importorskip("PIL.Image")


def photo(width: int, height: int, *, mode: str = "RGB") -> bytes:
    """압축이 잘 안 되도록 잡음을 넣은 큰 이미지."""
    import random

    im = PIL.new(mode, (width, height))
    rnd = random.Random(1)
    im.putdata([
        tuple(rnd.randrange(256) for _ in range(len(mode)))
        for _ in range(width * height)
    ])
    buffer = io.BytesIO()
    im.save(buffer, "PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------ 축소


def test_large_photo_is_shrunk_and_renamed():
    original = photo(2400, 1600)
    assert len(original) > 1_500_000

    data, name = web_ready(original, "what-is-clinic-2.png")

    assert len(data) < len(original)
    assert name.endswith(".jpg")
    with PIL.open(io.BytesIO(data)) as im:
        assert max(im.size) <= UPLOAD_MAX_EDGE


def test_small_image_is_left_alone():
    original = photo(80, 80)
    data, name = web_ready(original, "logo.png")

    assert data is original
    assert name == "logo.png"  # 로고를 다시 인코딩하면 오히려 지저분해집니다


def test_transparency_survives():
    original = photo(2000, 2000, mode="RGBA")
    data, name = web_ready(original, "badge.png")

    assert name.endswith(".png")  # JPEG로 바꾸면 배경이 검게 칠해집니다
    with PIL.open(io.BytesIO(data)) as im:
        assert im.mode in ("RGBA", "LA", "P")


def test_broken_bytes_fall_back_to_the_original():
    junk = b"\x00" * 2_000_000
    data, name = web_ready(junk, "broken.jpg")

    assert data is junk  # 화질보다 발행이 되는 쪽이 중요합니다
    assert name == "broken.jpg"


# ------------------------------------------------------------------ 중복 방지


class TimeoutOnceSession:
    """업로드 POST 는 타임아웃, 조회 GET 은 정상 응답."""

    def __init__(self, listing):
        self.headers: dict = {}
        self._listing = listing
        self.posts = 0

    def request(self, method, url, **kwargs):
        if method == "POST" and url.endswith("/wp/v2/media"):
            self.posts += 1
            raise requests.ReadTimeout("read timed out")
        if method == "POST":
            return Response({"id": 1})
        return Response(self._listing)


class Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.ok = True
        self.headers: dict = {}
        self.text = ""
        self.content = b"[]"

    def json(self):
        return self._payload


def stamp(minutes_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


def client(listing):
    session = TimeoutOnceSession(listing)
    return WordPressClient(CONFIG.wordpress, "user", "pw", session=session), session


def test_upload_is_not_resent_after_a_timeout():
    wp, session = client([{"id": 77, "slug": "what-is-clinic-2", "date_gmt": stamp(0.2),
                           "source_url": "https://blog.test/2.jpg"}])

    media = wp.upload_media("what-is-clinic-2.jpg", b"small", alt="설명")

    assert media.id == 77          # 서버에 올라간 것을 그대로 씁니다
    assert session.posts == 1      # 다시 보내지 않았습니다


def test_an_old_file_of_the_same_name_is_not_reused():
    # 지난 회차가 남긴 같은 이름의 파일을 집어오면, 사진을 바꿔 올렸을 때
    # 옛날 사진이 그대로 나갑니다.
    wp, session = client([{"id": 12, "slug": "what-is-clinic-2", "date_gmt": stamp(60 * 24)}])

    with pytest.raises(WordPressError):
        wp.upload_media("what-is-clinic-2.jpg", b"small")

    assert session.posts == 1


def test_failure_surfaces_when_nothing_landed():
    wp, session = client([])

    with pytest.raises(WordPressError):
        wp.upload_media("what-is-clinic-2.jpg", b"small")

    assert session.posts == 1
