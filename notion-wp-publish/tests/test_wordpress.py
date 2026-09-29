# -*- coding: utf-8 -*-
"""워드프레스 클라이언트 — 브리지가 '없는 것'과 사이트에 '닿지 못한 것'의 구분.

둘을 섞으면 네트워크가 막혀 있을 때도 "브리지 플러그인 없음 — 제한 모드"로
보고하게 됩니다. 실제로 그렇게 잘못 보고한 적이 있어 테스트로 묶어 둡니다.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notionwp.config import WordPressConfig
from notionwp.wordpress import WordPressClient, WordPressError


def _client() -> WordPressClient:
    return WordPressClient(WordPressConfig(base_url="https://blog.test"), "u", "p")


def _raising(message: str, status: int | None = None):
    def boom(*args, **kwargs):
        raise WordPressError(message, status=status)

    return boom


def test_a_404_means_the_bridge_is_missing(monkeypatch):
    """404 일 때만 '플러그인이 없다'로 봅니다."""
    client = _client()
    monkeypatch.setattr(client, "_request", _raising("404 rest_no_route", 404))
    assert client.bridge_ping(required=False) is None


def test_an_unreachable_site_is_not_blamed_on_the_plugin(monkeypatch):
    """네트워크가 막힌 것을 제한 모드로 삼키면 진짜 원인이 가려집니다."""
    client = _client()
    monkeypatch.setattr(client, "_request", _raising("Connection reset by peer"))
    with pytest.raises(WordPressError, match="Connection reset"):
        client.bridge_ping(required=False)


def test_an_auth_failure_is_not_blamed_on_the_plugin_either(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_request", _raising("401 rest_not_logged_in", 401))
    with pytest.raises(WordPressError, match="401"):
        client.bridge_ping(required=False)


def test_required_mode_still_explains_how_to_install(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_request", _raising("404 rest_no_route", 404))
    with pytest.raises(WordPressError, match="설치하고 활성화"):
        client.bridge_ping()


def test_the_extra_certs_survive_a_ca_bundle_environment_variable(monkeypatch, tmp_path):
    """보탠 중간 인증서는 요청까지 살아 있어야 합니다.

    requests 는 REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE 환경 변수를 session.verify
    보다 우선해서 씁니다. 번들을 session.verify 에만 넣어 두면 그런 환경에서는
    조용히 무시되고, 중간 인증서를 넣어 둔 보람도 없이 검증이 실패합니다.
    """
    bundle = tmp_path / "bundle.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----", encoding="utf-8")
    monkeypatch.setattr("notionwp.wordpress.ca_bundle", lambda: str(bundle))

    client = _client()
    seen: dict[str, object] = {}

    def capture(method, url, **kwargs):
        seen.update(kwargs)
        raise requests.ConnectionError("stop")  # 응답은 볼 필요가 없습니다

    monkeypatch.setattr(client.session, "request", capture)
    with pytest.raises(WordPressError):
        client._request("GET", "/wp/v2/posts", retry_network=False)

    assert seen.get("verify") == str(bundle), "요청에 번들이 실려야 환경 변수가 덮지 못합니다"


def test_nothing_to_add_leaves_the_request_alone(monkeypatch):
    """보탤 인증서가 없으면 기본 동작 그대로여야 합니다."""
    monkeypatch.setattr("notionwp.wordpress.ca_bundle", lambda: None)

    client = _client()
    seen: dict[str, object] = {}

    def capture(method, url, **kwargs):
        seen.update(kwargs)
        raise requests.ConnectionError("stop")

    monkeypatch.setattr(client.session, "request", capture)
    with pytest.raises(WordPressError):
        client._request("GET", "/wp/v2/posts", retry_network=False)

    assert "verify" not in seen


# --------------------------------------------------- Authorization 헤더가 지워지는 서버


def test_credentials_ride_along_in_a_second_header():
    """Authorization 을 지우는 서버가 있어 같은 값을 한 벌 더 보냅니다.

    그런 서버에서는 비밀번호가 맞아도 워드프레스가 아무것도 못 받아 401 이
    나고, 밖에서 보면 비밀번호가 틀린 것과 구분이 안 됩니다. 브리지
    플러그인(1.2.0+)이 이 헤더를 읽어 워드프레스가 보는 자리에 옮깁니다.
    """
    client = WordPressClient(WordPressConfig(base_url="https://blog.test"), "u", "p a s s")

    header = client.session.headers["X-Notion-Authorization"]

    assert header == "Basic " + base64.b64encode(b"u:pass").decode()


def test_the_second_header_carries_the_same_credentials_as_the_first():
    """두 헤더가 어긋나면 한쪽 경로에서만 로그인되는 유령 버그가 납니다."""
    client = WordPressClient(WordPressConfig(base_url="https://blog.test"), "u@x.test", "abcd efgh")

    request = requests.Request("GET", "https://blog.test", auth=client.session.auth).prepare()

    assert client.session.headers["X-Notion-Authorization"] == request.headers["Authorization"]
