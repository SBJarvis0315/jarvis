"""노션 REST 클라이언트. 필요한 만큼만 얇게 감쌉니다."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .config import NotionConfig

log = logging.getLogger(__name__)

API_ROOT = "https://api.notion.com/v1"
TIMEOUT = 30
MAX_RETRIES = 4


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, config: NotionConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": config.api_version,
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------ 저수준

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{API_ROOT}{path}"
        delay = 2.0

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES - 1:
                    raise NotionError(f"노션 요청 실패 {method} {path}: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            # 429/5xx 는 재시도, 그 외 4xx 는 즉시 실패.
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES - 1:
                    raise NotionError(
                        f"노션 요청 실패 {method} {path}: {resp.status_code} {resp.text[:300]}"
                    )
                wait = float(resp.headers.get("Retry-After", delay))
                log.warning("노션 %s 재시도 (%.0fs 대기)", resp.status_code, wait)
                time.sleep(wait)
                delay *= 2
                continue

            if not resp.ok:
                raise NotionError(
                    f"노션 요청 실패 {method} {path}: {resp.status_code} {resp.text[:500]}"
                )

            return resp.json()

        raise NotionError(f"노션 요청 실패 {method} {path}: 재시도 소진")

    # ------------------------------------------------------------------ 고수준

    def query_planner(self) -> list[dict[str, Any]]:
        """플래너의 모든 행을 가져옵니다.

        상태·날짜 필터를 서버에 맡기지 않고 전부 받아 로컬에서 검사합니다.
        게이트 조건이 여러 개라 어느 조건에서 걸렸는지 로그로 남겨야 하기 때문입니다.
        """
        if self.config.data_source_id and self.config.api_version >= "2025-09-03":
            path = f"/data_sources/{self.config.data_source_id}/query"
        else:
            path = f"/databases/{self.config.database_id}/query"

        rows: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            payload: dict[str, Any] = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor

            data = self._request("POST", path, json=payload)
            rows.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return rows

    def fetch_blocks(self, block_id: str, *, depth: int = 0) -> list[dict[str, Any]]:
        """블록과 그 자식들을 재귀적으로 가져옵니다.

        자식은 `_children` 키에 붙여둡니다 — 노션 API는 한 번에 한 계층만 주기 때문입니다.
        """
        if depth > 4:  # 원고 구조상 4단계를 넘어갈 일은 없습니다.
            return []

        blocks: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor

            data = self._request("GET", f"/blocks/{block_id}/children", params=params)
            blocks.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        for block in blocks:
            if block.get("has_children"):
                block["_children"] = self.fetch_blocks(block["id"], depth=depth + 1)

        return blocks

    def update_page(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})

    def create_page(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """DB에 행 하나를 추가합니다. 실행 로그 기록에만 씁니다."""
        return self._request(
            "POST",
            "/pages",
            json={"parent": {"database_id": database_id}, "properties": properties},
        )


# ------------------------------------------------------------- 속성 값 읽기/쓰기


def read_text(prop: dict[str, Any] | None) -> str:
    """rich_text / title 속성 → 평문."""
    if not prop:
        return ""

    from .richtext import plain_text, strip_markers

    nodes = prop.get("rich_text") or prop.get("title") or []
    # 제목에 굵은 글씨 마크업이 섞여 있는 경우가 있어 표시용 기호를 걷어냅니다.
    return strip_markers(plain_text(nodes))


def read_select(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    value = prop.get("select") or prop.get("status")
    return (value or {}).get("name", "") if isinstance(value, dict) else ""


def read_date(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    return ((prop.get("date") or {}).get("start")) or ""


def read_url(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    return prop.get("url") or ""


def write_status(name: str) -> dict[str, Any]:
    return {"status": {"name": name}}


def write_url(url: str) -> dict[str, Any]:
    return {"url": url}


def write_text(text: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}
