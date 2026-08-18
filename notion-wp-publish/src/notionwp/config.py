"""고객사별 설정. 비밀값은 파일이 아니라 환경변수에서만 읽습니다."""

from __future__ import annotations

import json
import os
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
    wp_user: str
    wp_app_password: str


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


def load_secrets(env: dict[str, str] | None = None) -> Secrets:
    src: Any = env if env is not None else os.environ

    missing = [
        name
        for name in ("NOTION_TOKEN", "WP_USER", "WP_APP_PASSWORD")
        if not src.get(name)
    ]
    if missing:
        raise ConfigError(
            "환경변수가 비어 있습니다: "
            + ", ".join(missing)
            + "\n  NOTION_TOKEN      노션 내부 통합(Integration) 시크릿"
            + "\n  WP_USER           워드프레스 사용자명"
            + "\n  WP_APP_PASSWORD   워드프레스 응용 프로그램 비밀번호"
        )

    return Secrets(
        notion_token=src["NOTION_TOKEN"],
        wp_user=src["WP_USER"],
        wp_app_password=src["WP_APP_PASSWORD"],
    )
