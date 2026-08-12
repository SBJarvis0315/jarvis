"""워드프레스 REST 클라이언트 (+ Notion Publish Bridge mu-plugin)."""

from __future__ import annotations

import logging
import mimetypes
import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .config import WordPressConfig

log = logging.getLogger(__name__)

TIMEOUT = 60
MAX_RETRIES = 4


class WordPressError(RuntimeError):
    pass


@dataclass
class Media:
    id: int
    url: str


@dataclass
class Post:
    id: int
    link: str
    status: str


class WordPressClient:
    def __init__(
        self,
        config: WordPressConfig,
        user: str,
        app_password: str,
        session: requests.Session | None = None,
    ):
        self.config = config
        self.session = session or requests.Session()
        # 응용 프로그램 비밀번호는 공백이 들어간 형태로 복사되는 경우가 많습니다.
        self.session.auth = HTTPBasicAuth(user, app_password.replace(" ", ""))

    # ------------------------------------------------------------------ 저수준

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.config.api_root}{path}"
        delay = 2.0

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES - 1:
                    raise WordPressError(f"워드프레스 요청 실패 {method} {path}: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 500 or resp.status_code == 429:
                if attempt == MAX_RETRIES - 1:
                    raise WordPressError(
                        f"워드프레스 요청 실패 {method} {path}: "
                        f"{resp.status_code} {resp.text[:300]}"
                    )
                time.sleep(delay)
                delay *= 2
                continue

            if not resp.ok:
                raise WordPressError(
                    f"워드프레스 요청 실패 {method} {path}: "
                    f"{resp.status_code} {resp.text[:500]}"
                )

            if not resp.content:
                return None
            return resp.json()

        raise WordPressError(f"워드프레스 요청 실패 {method} {path}: 재시도 소진")

    # ---------------------------------------------------------------- mu-plugin

    def bridge_ping(self) -> dict[str, Any]:
        """mu-plugin 설치 여부 확인. 없으면 명확한 안내와 함께 실패시킵니다."""
        try:
            return self._request("GET", "/notion-bridge/v1/ping")
        except WordPressError as exc:
            raise WordPressError(
                "Notion Publish Bridge mu-plugin 을 찾을 수 없습니다.\n"
                "  wp-mu-plugin/notion-publish-bridge.php 를 "
                "wp-content/mu-plugins/ 에 업로드해 주세요.\n"
                f"  (원본 오류: {exc})"
            ) from exc

    def lookup_by_notion_id(self, notion_page_id: str) -> dict[str, Any]:
        return self._request(
            "GET", "/notion-bridge/v1/lookup", params={"notion_page_id": notion_page_id}
        )

    def apply_seo(self, post_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/notion-bridge/v1/seo/{post_id}", json=payload)

    # -------------------------------------------------------------------- 미디어

    def upload_media(self, filename: str, data: bytes, alt: str = "") -> Media:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        created = self._request(
            "POST",
            "/wp/v2/media",
            data=data,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": mime,
            },
        )

        media_id = int(created["id"])

        # 가이드 ③ — 대체 텍스트는 업로드 직후 별도로 넣어야 반영됩니다.
        if alt:
            self._request("POST", f"/wp/v2/media/{media_id}", json={"alt_text": alt})

        return Media(id=media_id, url=created.get("source_url", ""))

    # ---------------------------------------------------------------------- 글

    def create_post(
        self,
        *,
        title: str,
        content: str,
        slug: str,
        status: str = "publish",
        categories: list[int] | None = None,
        featured_media: int | None = None,
    ) -> Post:
        payload: dict[str, Any] = {
            "title": title,
            "content": content,
            "slug": slug,
            "status": status,
        }
        if categories:
            payload["categories"] = categories
        if featured_media:
            payload["featured_media"] = featured_media

        created = self._request("POST", "/wp/v2/posts", json=payload)
        return Post(
            id=int(created["id"]),
            link=created.get("link", ""),
            status=created.get("status", status),
        )

    def update_post(self, post_id: int, fields: dict[str, Any]) -> Post:
        updated = self._request("POST", f"/wp/v2/posts/{post_id}", json=fields)
        return Post(
            id=int(updated["id"]),
            link=updated.get("link", ""),
            status=updated.get("status", ""),
        )

    def delete_post(self, post_id: int, *, force: bool = False) -> None:
        """발행 후 후속 단계가 실패했을 때 되돌리기 위한 용도."""
        self._request("DELETE", f"/wp/v2/posts/{post_id}", params={"force": str(force).lower()})

    def slug_taken(self, slug: str) -> bool:
        """워드프레스는 슬러그가 겹치면 조용히 -2 를 붙입니다. 미리 확인합니다."""
        found = self._request(
            "GET", "/wp/v2/posts", params={"slug": slug, "status": "any", "per_page": 1}
        )
        return bool(found)

    # ------------------------------------------------------------------ 카테고리

    def resolve_category(self, name: str) -> int | None:
        """이름으로 카테고리를 찾고, 없으면 만듭니다."""
        if not name:
            return None

        found = self._request(
            "GET", "/wp/v2/categories", params={"search": name, "per_page": 20}
        )
        for item in found or []:
            if item.get("name", "").strip() == name.strip():
                return int(item["id"])

        created = self._request("POST", "/wp/v2/categories", json={"name": name})
        log.info("카테고리를 새로 만들었습니다: %s", name)
        return int(created["id"])


def download(url: str, session: requests.Session | None = None) -> bytes:
    """노션 첨부를 내려받습니다.

    노션이 주는 S3 주소는 약 1시간 뒤 만료되므로, 링크를 그대로 워드프레스에
    넘기지 않고 반드시 내려받아 재업로드해야 합니다.
    """
    sess = session or requests
    resp = sess.get(url, timeout=TIMEOUT)
    if not resp.ok:
        raise WordPressError(f"이미지를 내려받지 못했습니다 ({resp.status_code}): {url[:120]}")
    return resp.content
