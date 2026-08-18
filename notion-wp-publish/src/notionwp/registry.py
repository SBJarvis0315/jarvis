"""고객사 발행 설정을 노션 '고객사 설정표'에서 읽어옵니다.

예전에는 고객사마다 `config/{이름}.json` 을 저장소에 만들어야 발행이 됐습니다.
그래서 새 고객사를 붙일 때마다 저장소 접근 권한이 있는 사람이 필요했고,
설정표와 JSON 두 군데에 같은 값(대상 유형 등)이 흩어져 어긋나기도 했습니다.

이제는 설정표 한 곳만 채우면 원고 생성과 발행이 모두 그 값을 씁니다.
저장소의 `config/defaults.json` 에는 전 고객사 공통값만 남습니다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import notion_api as napi
from .config import Config, ConfigError, NotionConfig
from .notion_api import NotionClient

log = logging.getLogger(__name__)

DEFAULTS_PATH = Path(__file__).resolve().parents[2] / "config" / "defaults.json"

_UUID = re.compile(r"[0-9a-fA-F]{32}")


def normalize_id(value: str) -> str:
    """URL을 통째로 붙여넣어도 32자리 ID만 뽑아냅니다."""
    raw = (value or "").strip().replace("-", "")
    match = _UUID.search(raw)
    return match.group(0) if match else ""


def parse_list(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[\n,]", text or "") if t.strip()]


def load_defaults(path: str | Path | None = None) -> Config:
    return Config.load(Path(path) if path else DEFAULTS_PATH)


def build_config(defaults: Config, row: dict[str, Any]) -> tuple[Config | None, str]:
    """설정표 행 하나 → 발행 설정. 발행 대상이 아니면 (None, 사유)."""
    rc = defaults.registry
    props = row.get("properties") or {}

    def text(key: str) -> str:
        return napi.read_text(props.get(rc.prop(key))).strip()

    client = text("client")
    if not client:
        return None, "고객사 이름이 비어 있음"

    state = napi.read_select(props.get(rc.prop("state")))
    if state != rc.state_active:
        return None, f"상태가 '{state or '미지정'}'"

    planner = normalize_id(text("planner"))
    if not planner:
        return None, "플래너 DB ID가 비었거나 형식이 맞지 않음"

    wp_url = text("wp_url")
    if not wp_url:
        # 원고 생성만 하는 고객사입니다. 오류가 아니라 정상 상태입니다.
        return None, "워드프레스 주소 없음 (원고 생성 전용)"
    if not wp_url.startswith("http"):
        wp_url = "https://" + wp_url

    notion = replace(
        defaults.notion,
        database_id=planner,
        type_filter=parse_list(text("types")) or list(defaults.notion.type_filter),
    )
    wordpress = replace(
        defaults.wordpress,
        base_url=wp_url.rstrip("/"),
        publisher_name=defaults.wordpress.publisher_name or client,
        author_name=defaults.wordpress.author_name or client,
        brand_suffix=defaults.wordpress.brand_suffix or client,
    )

    return replace(defaults, client=client, notion=notion, wordpress=wordpress), ""


def load_clients(
    token: str,
    *,
    defaults_path: str | Path | None = None,
    only: str = "",
    notion: NotionClient | None = None,
) -> list[Config]:
    """설정표에서 발행 대상 고객사 설정을 모두 읽어옵니다."""
    defaults = load_defaults(defaults_path)
    if not defaults.registry.database_id:
        raise ConfigError("defaults.json 에 registry.database_id 가 없습니다.")

    client = notion or NotionClient(
        token, NotionConfig(database_id=defaults.registry.database_id, api_version=defaults.notion.api_version)
    )
    rows = client.query_database(defaults.registry.database_id)

    configs: list[Config] = []
    for row in rows:
        cfg, reason = build_config(defaults, row)
        if cfg is None:
            # '일시중지'는 의도된 상태라 조용히 넘기고, 그 외에는 눈에 띄게 남깁니다.
            # 활성인데 발행 대상에서 빠지는 일이 조용히 지나가면 안 됩니다.
            name = napi.read_text((row.get("properties") or {}).get(defaults.registry.prop("client")))
            if reason.startswith("상태가"):
                log.debug("설정표 행 건너뜀 [%s]: %s", name, reason)
            else:
                log.info("발행 대상에서 제외 [%s]: %s", name or "(이름 없음)", reason)
            continue
        if only and only not in cfg.client:
            continue
        configs.append(cfg)

    log.info("설정표에서 발행 대상 %d개 고객사를 읽었습니다: %s",
             len(configs), ", ".join(c.client for c in configs) or "없음")
    return configs
