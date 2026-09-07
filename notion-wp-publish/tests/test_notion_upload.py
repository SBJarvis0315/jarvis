# -*- coding: utf-8 -*-
"""노션 파일 업로드 — 썸네일을 플래너 '썸네일' 칸에 붙이기 위한 경로."""

from __future__ import annotations

import pytest

from notionwp.config import NotionConfig
from notionwp.notion_api import NotionClient, NotionError, write_files


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.ok = status < 400
        self.text = text
        self.content = b"{}"

    def json(self):
        return self._payload


class FakeSession:
    """세션 헤더 병합까지 흉내 냅니다 — 여기서 한 번 물렸던 자리입니다."""

    def __init__(self, create=None, send=None):
        self.headers: dict[str, str] = {}
        self.create = create or FakeResponse({"id": "up-1"})
        self.send = send or FakeResponse({"status": "uploaded"})
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.create

    def post(self, url, **kwargs):
        merged = dict(self.headers)
        for key, value in (kwargs.get("headers") or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        # kwargs 를 뒤에 펼치면 방금 계산한 headers 를 도로 덮어씁니다.
        self.calls.append({"method": "POST", "url": url, **kwargs, "headers": merged})
        return self.send


def client(session):
    return NotionClient("secret", NotionConfig(database_id="db"), session=session)


def test_upload_returns_the_id():
    session = FakeSession()
    assert client(session).upload_file(b"png", "a.png", "image/png") == "up-1"


def test_json_content_type_is_cleared_for_the_multipart_send():
    """세션에 남은 application/json 을 그대로 보내면 노션이 400 을 냅니다.

    requests 는 요청별 헤더를 세션 헤더에 합치므로, 지우려면 None 을 넘겨야 합니다.
    """
    session = FakeSession()
    client(session).upload_file(b"png", "a.png", "image/png")

    send = session.calls[-1]
    assert "Content-Type" not in send["headers"]
    assert send["files"]["file"] == ("a.png", b"png", "image/png")


def test_missing_id_is_an_error():
    session = FakeSession(create=FakeResponse({}))
    with pytest.raises(NotionError, match="업로드 자리"):
        client(session).upload_file(b"png", "a.png", "image/png")


def test_a_failed_send_names_the_file():
    session = FakeSession(send=FakeResponse(status=413, text="too large"))
    with pytest.raises(NotionError, match="a.png"):
        client(session).upload_file(b"png", "a.png", "image/png")


def test_files_property_shape():
    assert write_files([("up-1", "썸네일.png")]) == {
        "files": [
            {"type": "file_upload", "file_upload": {"id": "up-1"}, "name": "썸네일.png"}
        ]
    }


def test_files_property_can_be_emptied():
    assert write_files([]) == {"files": []}
