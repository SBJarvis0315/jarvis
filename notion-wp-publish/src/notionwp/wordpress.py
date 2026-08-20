"""워드프레스 REST 클라이언트 (+ Notion Publish Bridge mu-plugin)."""

from __future__ import annotations

import html
import logging
import mimetypes
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .config import WordPressConfig

log = logging.getLogger(__name__)

TIMEOUT = 60
#: 이미지 업로드는 서버가 받아서 여러 크기로 재가공하는 시간이 붙습니다.
UPLOAD_TIMEOUT = 300
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: int = TIMEOUT,
        retry_network: bool = True,
        **kwargs: Any,
    ) -> Any:
        """`retry_network=False` 는 재시도하면 안 되는 요청(파일 업로드)에 씁니다.

        응답을 못 받았다고 해서 서버가 처리하지 않은 것은 아닙니다. 업로드를 그냥
        다시 보내면 같은 파일이 여러 장 생깁니다.
        """
        url = f"{self.config.api_root}{path}"
        delay = 2.0

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException as exc:
                if not retry_network or attempt == MAX_RETRIES - 1:
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
        from .images import web_ready

        data, filename = web_ready(data, filename)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        started = datetime.now(timezone.utc) - timedelta(minutes=1)

        try:
            created = self._request(
                "POST",
                "/wp/v2/media",
                data=data,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Type": mime,
                },
                timeout=UPLOAD_TIMEOUT,
                retry_network=False,
            )
        except WordPressError:
            # 응답이 안 왔을 뿐 서버에는 올라가 있을 수 있습니다. 다시 보내기 전에
            # 방금 올라온 파일이 있는지 확인합니다. 확인 없이 재시도하면 같은 사진이
            # 미디어 라이브러리에 여러 장 쌓입니다.
            created = self._find_recent_upload(filename, since=started)
            if created is None:
                raise
            log.warning(
                "업로드 응답을 받지 못했지만 서버에는 올라가 있어 그대로 씁니다: %s", filename
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

    def _find_recent_upload(self, filename: str, *, since: datetime) -> dict[str, Any] | None:
        """방금 올린 파일이 서버에 남아 있는지 확인합니다.

        `since` 이후에 만들어진 것만 인정합니다. 예전 회차가 남긴 같은 이름의 파일을
        집어오면, 노션에서 사진을 바꿔 올렸을 때 옛날 사진이 그대로 나갑니다.
        """
        slug = re.sub(r"\.[^.]+$", "", filename).lower()

        try:
            items = self._request(
                "GET", "/wp/v2/media", params={"search": slug, "per_page": 20}
            )
        except WordPressError:
            return None

        best: dict[str, Any] | None = None
        for item in items or []:
            item_slug = str(item.get("slug", ""))
            if item_slug != slug and not item_slug.startswith(slug + "-"):
                continue

            stamp = str(item.get("date_gmt") or "")
            try:
                created_at = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if created_at < since:
                continue

            if best is None or str(best.get("date_gmt")) < stamp:
                best = item

        return best

    def list_categories(self) -> dict[str, int]:
        """워드프레스에 있는 분류를 이름 → id 로 전부 가져옵니다."""
        names: dict[str, int] = {}
        page = 1

        while True:
            items = self._request(
                "GET", "/wp/v2/categories", params={"per_page": 100, "page": page}
            )
            if not items:
                break
            for item in items:
                # 워드프레스는 이름을 HTML 이스케이프해서 돌려줍니다 (&amp; 등).
                label = html.unescape(str(item.get("name", ""))).strip()
                if label:
                    names[label] = int(item["id"])
            if len(items) < 100:
                break
            page += 1

        return names

    def resolve_category(self, name: str) -> int | None:
        """이름으로 분류를 찾습니다. 없으면 만들지 않고 실패시킵니다.

        예전에는 없는 이름이면 그 이름으로 분류를 새로 만들었습니다. 편의 기능이었지만
        오타 하나로 유령 분류가 생기고 그 글만 거기 격리되는데도 발행은 성공으로
        보고돼서, 며칠 뒤에나 발견됐습니다. 지금은 발행을 멈추고 사람에게 넘깁니다.
        """
        if not name:
            return None

        existing = self.list_categories()
        found = existing.get(name.strip())
        if found is not None:
            return found

        raise WordPressError(
            f"워드프레스에 '{name}' 분류가 없습니다. "
            f"플래너의 카테고리를 워드프레스에 있는 이름으로 맞춰 주세요. "
            f"현재 있는 분류: {', '.join(sorted(existing)) or '(없음)'}"
        )


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
