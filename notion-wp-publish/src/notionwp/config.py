"""고객사별 설정. 비밀값은 파일이 아니라 환경변수에서만 읽습니다."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


@dataclass
class NotionConfig:
    database_id: str
    api_version: str = "2022-06-28"
    data_source_id: str = ""
    status_ready: str = "컨펌 진행 중"
    status_done: str = "게재완료"
    status_error: str = "발행 오류"
    type_filter: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)

    def prop(self, key: str) -> str:
        name = self.properties.get(key)
        if not name:
            raise ConfigError(f"설정에 notion.properties.{key} 가 없습니다.")
        return name


@dataclass
class WordPressConfig:
    base_url: str
    schema_mode: str = "rankmath"  # rankmath | jsonld
    default_category: str = ""
    category_map: dict[str, str] = field(default_factory=dict)
    #: 고객사 유튜브 채널 (UC… · @핸들 · 채널 주소). 비우면 영상을 넣지 않습니다.
    youtube_channel: str = ""
    publisher_name: str = ""
    publisher_logo: str = ""
    author_name: str = ""
    brand_suffix: str = ""

    @property
    def api_root(self) -> str:
        return self.base_url.rstrip("/") + "/wp-json"


@dataclass
class RenderConfig:
    spacer_height: int = 20
    spacer_before_headings: bool = True
    center_tables: bool = True

    #: 이 유형은 썸네일 한 장을 대표 이미지로 쓰면서 본문 맨 위에도 같이 넣습니다.
    #: 숏폼처럼 사진이 한 장뿐인 글을 위한 설정이며, 본문 이미지 칸은 비워둡니다.
    hero_image_types: list[str] = field(default_factory=list)


@dataclass
class RegistryConfig:
    """노션 '고객사 설정표'. 고객사별 발행 설정이 저장소가 아니라 여기에 있습니다."""

    database_id: str = ""
    state_active: str = "활성"
    properties: dict[str, str] = field(
        default_factory=lambda: {
            "client": "고객사",
            "state": "상태",
            "planner": "플래너 DB ID",
            "types": "대상 유형",
            "wp_url": "워드프레스 주소",
            "youtube": "유튜브 채널",
        }
    )

    def prop(self, key: str) -> str:
        name = self.properties.get(key)
        if not name:
            raise ConfigError(f"설정에 registry.properties.{key} 가 없습니다.")
        return name


@dataclass
class RunLogConfig:
    """노션 '자동화 실행 로그' DB. `database_id` 가 비어 있으면 로그를 남기지 않습니다."""

    database_id: str = ""
    #: 같은 DB에 1단계(원고 생성) 로그가 함께 쌓이므로, 어느 단계인지 표시합니다.
    stage: str = "워드프레스 발행"
    properties: dict[str, str] = field(
        default_factory=lambda: {
            "title": "실행",
            "date": "실행일시",
            "client": "고객사",
            "count": "처리 건수",
            "result": "결과",
            "detail": "상세",
            "stage": "단계",
        }
    )

    def prop(self, key: str) -> str:
        name = self.properties.get(key)
        if not name:
            raise ConfigError(f"설정에 run_log.properties.{key} 가 없습니다.")
        return name


@dataclass
class Secrets:
    notion_token: str
    #: 전 고객사 공용 워드프레스 계정. 고객사별 값이 있으면 그쪽이 우선입니다.
    wp_user: str = ""
    wp_app_password: str = ""


@dataclass
class Config:
    client: str
    notion: NotionConfig
    wordpress: WordPressConfig
    render: RenderConfig = field(default_factory=RenderConfig)
    run_log: RunLogConfig = field(default_factory=RunLogConfig)
    registry: RegistryConfig = field(default_factory=RegistryConfig)

    @classmethod
    def load(cls, path: str | Path) -> Config:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            return cls(
                client=raw.get("client", ""),
                notion=NotionConfig(**raw["notion"]),
                wordpress=WordPressConfig(**raw["wordpress"]),
                render=RenderConfig(**raw.get("render", {})),
                run_log=RunLogConfig(**raw.get("run_log", {})),
                registry=RegistryConfig(**raw.get("registry", {})),
            )
        except (KeyError, TypeError) as exc:
            raise ConfigError(f"설정 파일을 읽지 못했습니다 ({path}): {exc}") from exc


#: 주소에서 이름을 뽑을 때 떼어낼 꼬리표. 앞에서부터가 아니라 뒤에서부터 벗깁니다.
_DOMAIN_TAILS = {
    "com", "net", "org", "co", "kr", "jp", "io", "me", "biz", "info",
    "shop", "site", "dev", "ai", "app", "kro", "or", "ne", "go", "pe",
}


def credential_key(base_url: str) -> str:
    """워드프레스 주소 → 환경변수 이름에 붙일 고객사 키.

        https://blog.cleartone.co.kr  →  CLEARTONE
        https://example.com           →  EXAMPLE

    고객사마다 워드프레스 계정이 다르므로 자격증명도 고객사별로 나뉘어야 합니다.
    설정표에 컬럼을 하나 더 두는 대신 주소에서 키를 뽑아, 사람이 관리할 값을
    늘리지 않았습니다.
    """
    host = (base_url or "").strip().lower()
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0].split(":")[0]
    if not host:
        return ""

    labels = [l for l in host.split(".") if l]
    while len(labels) > 1 and labels[-1] in _DOMAIN_TAILS:
        labels.pop()

    return re.sub(r"[^A-Z0-9]", "_", labels[-1].upper()) if labels else ""


def wp_credentials(
    base_url: str, secrets: Secrets, env: dict[str, str] | None = None
) -> tuple[str, str]:
    """이 고객사에 쓸 워드프레스 계정. 고객사 전용 값이 없으면 공용 값을 씁니다."""
    src: Any = env if env is not None else os.environ
    key = credential_key(base_url)

    user = (src.get(f"WP_USER_{key}") or "").strip() if key else ""
    password = (src.get(f"WP_APP_PASSWORD_{key}") or "").strip() if key else ""

    # 한쪽만 넣어두면 섞여서 엉뚱한 계정으로 로그인합니다. 둘 다 있을 때만 씁니다.
    if user and password:
        return user, password

    if user or password:
        raise ConfigError(
            f"'{base_url}' 용 자격증명이 반쪽만 있습니다. "
            f"WP_USER_{key} 와 WP_APP_PASSWORD_{key} 를 둘 다 넣어 주세요."
        )

    if secrets.wp_user and secrets.wp_app_password:
        return secrets.wp_user, secrets.wp_app_password

    raise ConfigError(
        f"'{base_url}' 에 쓸 워드프레스 계정이 없습니다.\n"
        f"  환경변수에 아래 두 개를 넣어 주세요:\n"
        f"    WP_USER_{key}=워드프레스 사용자명\n"
        f"    WP_APP_PASSWORD_{key}=응용 프로그램 비밀번호\n"
        f"  (고객사가 한 곳뿐이면 WP_USER · WP_APP_PASSWORD 로 넣어도 됩니다)"
    )


def load_secrets(env: dict[str, str] | None = None) -> Secrets:
    """공용 비밀값. 워드프레스 계정은 고객사별로 따로 둘 수 있어 여기서는 선택입니다."""
    src: Any = env if env is not None else os.environ

    if not src.get("NOTION_TOKEN"):
        raise ConfigError(
            "환경변수가 비어 있습니다: NOTION_TOKEN"
            "\n  NOTION_TOKEN      노션 내부 통합(Integration) 시크릿"
        )

    return Secrets(
        notion_token=src["NOTION_TOKEN"],
        wp_user=(src.get("WP_USER") or "").strip(),
        wp_app_password=(src.get("WP_APP_PASSWORD") or "").strip(),
    )
