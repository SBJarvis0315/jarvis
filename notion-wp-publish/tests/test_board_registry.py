"""자체 게시판 고객사 — 설정표 해석, 자격증명, 게이트 차이."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp.board import BoardError, BoardProfile
from notionwp.config import ConfigError, board_credentials, credential_key
from notionwp.publish import check_properties
from notionwp.registry import build_config, load_clients
from test_gate_schema import DEFAULTS, TODAY, complete_page, text_prop
from test_registry import FakeNotion

ADMIN = "https://www.zeroclinic1.com/admin/board/main.php"


def board_row(**overrides) -> dict:
    """설정표의 제로클리닉 행. 워드프레스 주소는 비고 게시판 주소만 있습니다."""
    values = {
        "고객사": "제로클리닉",
        "상태": "활성",
        "플래너 DB ID": "97668fa206ff837f90b80140f63456e4",
        "대상 유형": "롱폼, 숏폼",
        "워드프레스 주소": "",
        "유튜브 채널": "",
        "게시판 주소": ADMIN,
    }
    values.update(overrides)
    props: dict = {
        "고객사": {"type": "title", "title": [{"plain_text": values["고객사"], "annotations": {}}]},
        "상태": {"type": "select", "select": {"name": values["상태"]}},
    }
    for key in ("플래너 DB ID", "대상 유형", "워드프레스 주소", "유튜브 채널", "게시판 주소"):
        props[key] = {"type": "rich_text", "rich_text": [{"plain_text": values[key], "annotations": {}}]}
    return {"id": "row", "properties": props}


# ------------------------------------------------------------------ 설정표 해석


def test_board_row_is_a_board_client():
    cfg, reason = build_config(DEFAULTS, board_row(), platform="board")
    assert reason == ""
    assert cfg.platform == "board"
    assert cfg.board.admin_url == ADMIN
    assert cfg.wordpress.base_url == ""


def test_board_row_is_excluded_from_the_wordpress_stage():
    """워드프레스 루틴이 게시판 고객사를 집어 들면 mu-plugin 오류로 넘어집니다."""
    cfg, reason = build_config(DEFAULTS, board_row())
    assert cfg is None
    assert "자체 게시판" in reason


def test_wordpress_row_is_excluded_from_the_board_stage():
    cfg, reason = build_config(
        DEFAULTS,
        board_row(**{"게시판 주소": "", "워드프레스 주소": "https://blog.example.com"}),
        platform="board",
    )
    assert cfg is None
    assert "워드프레스 고객사" in reason


def test_generation_only_row_has_no_platform():
    cfg, reason = build_config(DEFAULTS, board_row(**{"게시판 주소": ""}), platform="board")
    assert cfg is None
    assert "원고 생성 전용" in reason


def test_both_addresses_is_an_error_not_a_double_publish():
    cfg, reason = build_config(
        DEFAULTS, board_row(**{"워드프레스 주소": "https://blog.example.com"}), platform="board"
    )
    assert cfg is None
    assert "둘 다" in reason


def test_thumbnail_stage_takes_board_clients_too():
    cfg, _ = build_config(DEFAULTS, board_row(), platform=None)
    assert cfg is not None and cfg.client == "제로클리닉"


def test_bare_admin_host_gets_https():
    row = board_row(**{"게시판 주소": "www.zeroclinic1.com/admin/board/main.php/"})
    cfg, _ = build_config(DEFAULTS, row, platform="board")
    assert cfg.board.admin_url == "https://www.zeroclinic1.com/admin/board/main.php"


def test_unknown_platform_is_rejected():
    with pytest.raises(ConfigError, match="모르는 발행처"):
        build_config(DEFAULTS, board_row(), platform="naver")


def test_load_clients_filters_by_platform():
    from test_gate_schema import registry_row

    notion = FakeNotion([registry_row(), board_row()])
    wp = load_clients("tok", notion=notion, platform="wordpress")
    board = load_clients("tok", notion=notion, platform="board")
    both = load_clients("tok", notion=notion, platform=None)

    assert [c.client for c in wp] == ["클리어톤의원"]
    assert [c.client for c in board] == ["제로클리닉"]
    assert sorted(c.client for c in both) == ["제로클리닉", "클리어톤의원"]


# ------------------------------------------------------------------ 자격증명


def test_credential_key_from_admin_url():
    assert credential_key(ADMIN) == "ZEROCLINIC1"


def test_board_credentials_come_from_client_specific_env():
    env = {"BOARD_USER_ZEROCLINIC1": "admin", "BOARD_PASSWORD_ZEROCLINIC1": "pw"}
    assert board_credentials(ADMIN, env) == ("admin", "pw")


def test_board_credentials_have_no_shared_fallback():
    """게시판은 사이트마다 계정이 달라, 다른 고객사 관리자에 들어가는 실수를 막습니다."""
    with pytest.raises(ConfigError, match="BOARD_USER_ZEROCLINIC1"):
        board_credentials(ADMIN, {"BOARD_USER": "x", "BOARD_PASSWORD": "y"})


def test_half_credentials_are_refused():
    with pytest.raises(ConfigError, match="반쪽"):
        board_credentials(ADMIN, {"BOARD_USER_ZEROCLINIC1": "admin"})


# ------------------------------------------------------------------ 게이트 차이


def test_board_gate_does_not_need_a_slug():
    cfg, _ = build_config(DEFAULTS, board_row(), platform="board")
    page = complete_page(**{"슬러그": text_prop("")})
    assert not check_properties(cfg, page, on=TODAY).ok
    assert check_properties(cfg, page, on=TODAY, require_slug=False).ok


def test_board_gate_still_needs_meta_description():
    cfg, _ = build_config(DEFAULTS, board_row(), platform="board")
    page = complete_page(**{"메타디스크립션": text_prop("")})
    cand = check_properties(cfg, page, on=TODAY, require_slug=False)
    assert any("메타디스크립션" in r for r in cand.reasons)


# ------------------------------------------------------------------ 프로파일


def test_zeroclinic_profile_is_checked_in():
    profile = BoardProfile.load(ADMIN)
    assert profile.host == "www.zeroclinic1.com"
    assert profile.tab == "블로그"
    assert profile.public_link("161") == "https://www.zeroclinic1.com/htm/boardseo_read.php?id=161"
    assert 0 < profile.hit_min < profile.hit_max


def test_missing_profile_points_at_inspect(tmp_path):
    with pytest.raises(BoardError, match="board-inspect"):
        BoardProfile.load("https://new-clinic.example/admin/", directory=tmp_path)


def test_profile_round_trips(tmp_path):
    profile = BoardProfile(host="a.example", public_url="https://a.example/read?id={id}", tab="공지")
    profile.save(tmp_path)
    loaded = BoardProfile.load("https://a.example/admin/list.php", directory=tmp_path)
    assert loaded.tab == "공지"
    # 설정표의 주소가 프로파일 파일의 값보다 우선합니다.
    assert loaded.admin_url == "https://a.example/admin/list.php"


def test_profile_is_found_with_or_without_www():
    """설정표에 www 를 빼고 적어도 같은 프로파일을 찾습니다."""
    profile = BoardProfile.load("https://zeroclinic1.com/admin/board/main.php")
    assert profile.host == "www.zeroclinic1.com"
    assert profile.login_url.endswith("/admin/Login.php")
