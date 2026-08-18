"""고객사 설정표에서 발행 설정을 읽어오는 경로.

저장소에 고객사별 JSON 을 만들지 않아도 발행이 되는지, 그리고 표에 오타가 있을 때
조용히 빠지지 않고 사유가 남는지를 확인합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp.registry import build_config, load_clients, normalize_id
from test_gate_schema import DEFAULTS, DEFAULTS_PATH, registry_row


class FakeNotion:
    def __init__(self, rows):
        self._rows = rows
        self.queried: list[str] = []

    def query_database(self, database_id):
        self.queried.append(database_id)
        return self._rows


# ------------------------------------------------------------------ 값 해석


def test_planner_id_accepts_a_pasted_url():
    url = "https://www.notion.so/leadgen-lab/97668fa206ff837f90b80140f63456e4?v=abc"
    assert normalize_id(url) == "97668fa206ff837f90b80140f63456e4"
    assert normalize_id("9766-8fa2-06ff") == ""


# ------------------------------------------------------------------ 행 → 설정


def test_active_row_becomes_a_publishable_config():
    cfg, reason = build_config(DEFAULTS, registry_row())

    assert reason == ""
    assert cfg.client == "클리어톤의원"
    assert cfg.notion.database_id == "97668fa206ff837f90b80140f63456e4"
    assert cfg.wordpress.base_url == "https://blog.cleartone.co.kr"
    assert cfg.notion.type_filter == ["롱폼", "숏폼", "브랜드 엔티티", "제품 엔티티"]
    # 공통 기본값은 그대로 따라옵니다.
    assert cfg.render.hero_image_types == ["숏폼"]
    assert cfg.run_log.database_id
    # 고객사 이름이 브랜드 표기의 기본값이 됩니다.
    assert cfg.wordpress.brand_suffix == "클리어톤의원"


def test_paused_row_is_skipped():
    cfg, reason = build_config(DEFAULTS, registry_row(상태="일시중지"))
    assert cfg is None
    assert "상태가" in reason


def test_row_without_wordpress_address_is_generation_only():
    cfg, reason = build_config(DEFAULTS, registry_row(**{"워드프레스 주소": ""}))
    assert cfg is None
    assert "원고 생성 전용" in reason


def test_bare_domain_gets_https():
    cfg, _ = build_config(DEFAULTS, registry_row(**{"워드프레스 주소": "blog.example.co.kr/"}))
    assert cfg.wordpress.base_url == "https://blog.example.co.kr"


def test_broken_planner_id_is_reported_not_silently_dropped():
    cfg, reason = build_config(DEFAULTS, registry_row(**{"플래너 DB ID": "여기에 붙여넣기"}))
    assert cfg is None
    assert "플래너 DB ID" in reason


def test_planner_columns_come_from_the_shared_template():
    # 플래너 컬럼 이름은 전 고객사가 통일해 쓰므로 고객사별로 달라지지 않습니다.
    cfg, _ = build_config(DEFAULTS, registry_row())
    assert cfg.notion.prop("thumbnail") == "썸네일"
    assert cfg.notion.prop("title") == "제목"


def test_category_name_passes_through_untouched():
    # 노션 카테고리 옵션을 워드프레스에 이미 있는 이름으로 맞춰 쓰기 때문에
    # 중간에 이름을 바꾸지 않습니다.
    cfg, _ = build_config(DEFAULTS, registry_row())
    assert cfg.wordpress.category_map == {}


def test_empty_type_filter_falls_back_to_defaults():
    cfg, _ = build_config(DEFAULTS, registry_row(**{"대상 유형": ""}))
    assert cfg.notion.type_filter == DEFAULTS.notion.type_filter


# ------------------------------------------------------------------ 목록 읽기


def test_load_clients_reads_only_active_rows():
    notion = FakeNotion(
        [
            registry_row(),
            registry_row(고객사="쉬는곳", 상태="일시중지"),
            registry_row(고객사="주소없는곳", **{"워드프레스 주소": ""}),
        ]
    )
    configs = load_clients("token", defaults_path=DEFAULTS_PATH, notion=notion)

    assert [c.client for c in configs] == ["클리어톤의원"]
    assert notion.queried == [DEFAULTS.registry.database_id]


def test_client_filter_matches_by_substring():
    notion = FakeNotion([registry_row(), registry_row(고객사="다른의원")])
    configs = load_clients("token", defaults_path=DEFAULTS_PATH, only="클리어톤", notion=notion)
    assert [c.client for c in configs] == ["클리어톤의원"]
