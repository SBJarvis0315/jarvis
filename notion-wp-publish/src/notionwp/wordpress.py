"""워드프레스 REST 클라이언트 (+ Notion Publish Bridge mu-plugin)."""

from __future__ import annotations

import base64
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

from .posttype import DEFAULT as DEFAULT_TARGET
from .posttype import INTERNAL_POST_TYPES, INTERNAL_TAXONOMIES, Target
from .trust import ca_bundle

log = logging.getLogger(__name__)

TIMEOUT = 60
#: 이미지 업로드는 서버가 받아서 여러 크기로 재가공하는 시간이 붙습니다.
UPLOAD_TIMEOUT = 300
MAX_RETRIES = 4


class WordPressError(RuntimeError):
    """워드프레스 요청 실패.

    `status` 는 서버가 응답했을 때의 HTTP 코드입니다. 아예 닿지 못한 경우
    (DNS·방화벽·연결 끊김)에는 None 입니다. 브리지가 '없는 것'과 사이트에
    '닿지 못한 것'을 가르는 데 씁니다 — 둘을 섞으면 네트워크가 막힌 것을
    플러그인 탓으로 잘못 보고하게 됩니다.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


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
        password = app_password.replace(" ", "")
        self.session.auth = HTTPBasicAuth(user, password)

        # Authorization 헤더를 PHP까지 넘기지 않는 서버가 있습니다. 그런 곳에서는
        # 비밀번호가 맞아도 워드프레스가 아무것도 못 받아 401 만 돌려주고, 밖에서
        # 보면 비밀번호가 틀린 것과 구분이 안 됩니다. 같은 값을 헤더 하나에 더
        # 실어 보내고, 브리지 플러그인(1.2.0+)이 그걸 워드프레스가 보는 자리에
        # 옮겨 놓습니다. 헤더가 멀쩡히 가는 고객사에서는 그냥 무시됩니다.
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.session.headers["X-Notion-Authorization"] = f"Basic {token}"

        # 인증서 사슬을 잘못 설치해 둔 고객사 서버가 있습니다. 빠진 중간 인증서를
        # 저장소에 두고 여기서 보탭니다. 검증을 끄는 것이 아니라 빈 칸을 채우는
        # 것이며, 보탤 것이 없으면 기본 동작 그대로입니다.
        #
        # 번들은 요청마다 넘겨야 합니다. requests 는 REQUESTS_CA_BUNDLE /
        # CURL_CA_BUNDLE 환경 변수를 session.verify 보다 우선해서 씁니다. 그런
        # 환경(프록시를 쓰는 곳이 대표적)에서는 session.verify 에만 넣어 두면
        # 조용히 무시되고, 보탠 중간 인증서가 없는 셈이 됩니다. 요청에 직접 넘긴
        # 값은 환경 변수보다 우선하므로 어디서 돌려도 같게 동작합니다.
        self._ca_bundle = ca_bundle()

        #: discover_targets() 의 결과. 회차당 한 번만 물어봅니다.
        self._targets: list[Target] | None = None

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
        if self._ca_bundle:
            kwargs.setdefault("verify", self._ca_bundle)

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
                    f"{resp.status_code} {resp.text[:500]}",
                    status=resp.status_code,
                )

            if not resp.content:
                return None
            return resp.json()

        raise WordPressError(f"워드프레스 요청 실패 {method} {path}: 재시도 소진")

    # ---------------------------------------------------------------- mu-plugin

    def bridge_ping(self, *, required: bool = True) -> dict[str, Any] | None:
        """브리지 플러그인 설치 여부 확인.

        `required=False` 면 없을 때 예외 대신 None 을 돌려줍니다. 고객사 서버의
        웹방화벽이 플러그인 설치를 막아 브리지를 넣지 못하는 곳이 있어서,
        발행 자체는 계속하고 브리지가 하던 일만 빼는 제한 모드로 넘어가기
        위한 것입니다. 나중에 플러그인이 들어가면 저절로 원래대로 돌아옵니다.
        """
        try:
            return self._request("GET", "/notion-bridge/v1/ping")
        except WordPressError as exc:
            # 404 만 '플러그인이 없다'는 뜻입니다. 사이트에 닿지 못했거나 인증이
            # 막힌 것이라면 그대로 터뜨려야 합니다 — 제한 모드로 넘어가 봐야
            # 이어지는 요청도 같은 이유로 전부 실패하고, 원인만 가려집니다.
            if exc.status != 404:
                # 닿지 못했거나 인증이 막힌 것입니다. 플러그인 탓으로 바꿔 말하면
                # 진짜 원인(네트워크 허용 도메인 누락 등)이 가려집니다.
                raise
            if not required:
                log.warning("브리지 플러그인을 찾지 못했습니다. 제한 모드로 진행합니다: %s", exc)
                return None
            raise WordPressError(
                "Notion Publish Bridge 플러그인을 찾을 수 없습니다.\n"
                "  wp-mu-plugin/notion-publish-bridge-1.2.0.zip 을 워드프레스에 설치하고 "
                "활성화해 주세요.\n"
                "  이 사이트가 워드프레스가 아니라 자체 홈페이지 게시판이라면, "
                "boards/<호스트>.json 프로파일을 만들어야 게시판 발행이 집어갑니다.\n"
                f"  (원본 오류: {exc})",
                status=exc.status,
            ) from exc

    def lookup_by_notion_id(self, notion_page_id: str) -> dict[str, Any]:
        return self._request(
            "GET", "/notion-bridge/v1/lookup", params={"notion_page_id": notion_page_id}
        )

    def lookup_by_slug(self, slug: str) -> dict[str, Any]:
        """브리지가 없을 때 쓰는 중복 확인. 워드프레스 기본 REST 만 씁니다.

        노션 페이지 ID 를 글에 심어 두는 일이 브리지 몫이라, 브리지가 없으면
        그 ID 로 찾을 수가 없습니다. 대신 슬러그로 찾습니다 — 우리가 플래너의
        슬러그를 그대로 글 주소에 쓰므로 같은 원고면 같은 슬러그가 됩니다.
        `lookup_by_notion_id` 와 같은 모양으로 돌려줍니다.
        """
        if not slug:
            return {"found": False}

        posts = self._request(
            "GET",
            "/wp/v2/posts",
            params={
                "slug": slug,
                "status": "publish,draft,pending,future,private",
                "per_page": 1,
            },
        )
        if not posts:
            return {"found": False}

        post = posts[0]
        return {
            "found": True,
            "post_id": post.get("id"),
            "status": post.get("status", ""),
            "link": post.get("link", ""),
        }

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
        target: Target = DEFAULT_TARGET,
    ) -> Post:
        payload: dict[str, Any] = {
            "title": title,
            "content": content,
            "slug": slug,
            "status": status,
        }
        if categories:
            # 별도 글 종류는 분류를 담는 필드 이름도 다릅니다 (glossary_cat 등).
            payload[target.taxonomy_field] = categories
        if featured_media:
            payload["featured_media"] = featured_media

        created = self._request("POST", target.posts_path, json=payload)
        return Post(
            id=int(created["id"]),
            link=created.get("link", ""),
            status=created.get("status", status),
        )

    def update_post(
        self, post_id: int, fields: dict[str, Any], *, target: Target = DEFAULT_TARGET
    ) -> Post:
        updated = self._request("POST", f"{target.posts_path}/{post_id}", json=fields)
        return Post(
            id=int(updated["id"]),
            link=updated.get("link", ""),
            status=updated.get("status", ""),
        )

    def delete_post(
        self, post_id: int, *, force: bool = False, target: Target = DEFAULT_TARGET
    ) -> None:
        """발행 후 후속 단계가 실패했을 때 되돌리기 위한 용도."""
        self._request(
            "DELETE", f"{target.posts_path}/{post_id}", params={"force": str(force).lower()}
        )

    def slug_taken(self, slug: str, *, target: Target = DEFAULT_TARGET) -> bool:
        """워드프레스는 슬러그가 겹치면 조용히 -2 를 붙입니다. 미리 확인합니다."""
        found = self._request(
            "GET", target.posts_path, params={"slug": slug, "status": "any", "per_page": 1}
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

    def list_categories(self, *, target: Target = DEFAULT_TARGET) -> dict[str, int]:
        """그 글 종류의 분류를 이름 → id 로 전부 가져옵니다."""
        names: dict[str, int] = {}
        page = 1

        while True:
            items = self._request(
                "GET", target.taxonomy_path, params={"per_page": 100, "page": page}
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

    def discover_targets(self) -> list[Target]:
        """이 사이트가 쓰는 글 종류를 REST 에서 직접 읽어 후보로 만듭니다.

        개발사가 '용어사전'·'백과사전' 같은 별도 글 종류를 만들어 둔 사이트가
        있습니다. 겉보기 메뉴는 일반 카테고리와 똑같아서, 고객사를 붙일 때
        사람이 알아채기 어렵습니다. 실제로 비컴·쉬즈메디 둘 다 발행이 막히고
        나서야 드러났습니다. 그래서 사이트에 직접 물어봅니다.

        `posttypes/<고객사>.json` 에 적어 둔 대응표가 있으면 그쪽이 우선입니다.
        여기는 적어 둔 것이 없을 때 쓰는 길입니다.
        """
        if self._targets is not None:
            return self._targets

        types = self._request("GET", "/wp/v2/types") or {}
        taxonomies = self._request("GET", "/wp/v2/taxonomies") or {}

        # 분류 체계의 REST 이름은 따로 물어봐야 압니다 (category → categories).
        tax_rest = {
            name: str(spec.get("rest_base") or name)
            for name, spec in taxonomies.items()
        }

        targets: list[Target] = []
        for name, spec in types.items():
            if name in INTERNAL_POST_TYPES:
                continue
            rest_base = str(spec.get("rest_base") or "").strip()
            if not rest_base:
                continue
            label = str(spec.get("name") or name).strip()
            for taxonomy in spec.get("taxonomies") or []:
                if taxonomy in INTERNAL_TAXONOMIES:
                    continue
                rest = tax_rest.get(taxonomy, taxonomy)
                targets.append(
                    Target(
                        rest_base=rest_base,
                        taxonomy_rest_base=rest,
                        taxonomy_field=rest,
                        label=label,
                    )
                )

        self._targets = targets
        return targets

    def find_target_for_category(self, name: str) -> tuple[Target, int] | None:
        """분류 이름 하나로 '어느 글 종류의 분류인지' 를 찾습니다.

        딱 한 곳에서만 나올 때만 돌려줍니다. 여러 글 종류에 같은 이름이 있으면
        어느 쪽인지 기계가 정할 수 없으므로, 골라 주지 않고 사람에게 넘깁니다.
        """
        wanted = (name or "").strip()
        if not wanted:
            return None

        matches: list[tuple[Target, int]] = []
        for target in self.discover_targets():
            if target.is_default:
                # 일반 카테고리는 이미 확인한 뒤에 여기까지 온 것입니다.
                continue
            try:
                found = self.list_categories(target=target).get(wanted)
            except WordPressError:
                continue
            if found is not None:
                matches.append((target, found))

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            where = ", ".join(f"{t.label}({t.rest_base})" for t, _ in matches)
            raise WordPressError(
                f"'{wanted}' 분류가 여러 글 종류에 있습니다: {where}. "
                f"어느 쪽에 올릴지는 사람이 정해야 합니다 — "
                f"posttypes/<고객사>.json 에 게시판 대응을 적어 주세요."
            )

        return None

    def resolve_category(self, name: str, *, target: Target = DEFAULT_TARGET) -> int | None:
        """이름으로 분류를 찾습니다. 없으면 만들지 않고 실패시킵니다.

        예전에는 없는 이름이면 그 이름으로 분류를 새로 만들었습니다. 편의 기능이었지만
        오타 하나로 유령 분류가 생기고 그 글만 거기 격리되는데도 발행은 성공으로
        보고돼서, 며칠 뒤에나 발견됐습니다. 지금은 발행을 멈추고 사람에게 넘깁니다.
        """
        if not name:
            return None

        existing = self.list_categories(target=target)
        found = existing.get(name.strip())
        if found is not None:
            return found

        where = f"'{target.label}'" if target.label else "워드프레스"
        raise WordPressError(
            f"{where} 에 '{name}' 분류가 없습니다. "
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
