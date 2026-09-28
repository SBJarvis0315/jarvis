# -*- coding: utf-8 -*-
"""워드프레스 클라이언트 — 브리지가 '없는 것'과 사이트에 '닿지 못한 것'의 구분.

둘을 섞으면 네트워크가 막혀 있을 때도 "브리지 플러그인 없음 — 제한 모드"로
보고하게 됩니다. 실제로 그렇게 잘못 보고한 적이 있어 테스트로 묶어 둡니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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
