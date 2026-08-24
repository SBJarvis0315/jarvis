"""고객사별 워드프레스 계정.

고객사마다 워드프레스가 다른 설치본이라 계정도 다릅니다. 전에는 환경변수 한 벌만
읽어서, 두 번째 고객사를 붙이면 첫 고객사 계정으로 로그인을 시도하다 401 로 떨어졌습니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp.config import ConfigError, Secrets, credential_key, load_secrets, wp_credentials

SHARED = Secrets(notion_token="ntn", wp_user="공용계정", wp_app_password="공용비번")
NO_WP = Secrets(notion_token="ntn")


# ------------------------------------------------------------------ 키 뽑기


def test_key_comes_from_the_registrable_name():
    assert credential_key("https://blog.cleartone.co.kr") == "CLEARTONE"
    assert credential_key("https://example.com") == "EXAMPLE"
    assert credential_key("http://www.abc-clinic.kr/") == "ABC_CLINIC"
    assert credential_key("https://m.test.co.jp:8080") == "TEST"


def test_key_is_empty_when_there_is_no_address():
    assert credential_key("") == ""
    assert credential_key("   ") == ""


# ------------------------------------------------------------------ 계정 고르기


def test_client_specific_credentials_win():
    env = {"WP_USER_CLEARTONE": "전용계정", "WP_APP_PASSWORD_CLEARTONE": "전용비번"}
    assert wp_credentials("https://blog.cleartone.co.kr", SHARED, env) == ("전용계정", "전용비번")


def test_falls_back_to_the_shared_pair():
    assert wp_credentials("https://blog.cleartone.co.kr", SHARED, {}) == ("공용계정", "공용비번")


def test_each_client_gets_its_own():
    env = {
        "WP_USER_CLEARTONE": "A계정", "WP_APP_PASSWORD_CLEARTONE": "A비번",
        "WP_USER_EXAMPLE": "B계정", "WP_APP_PASSWORD_EXAMPLE": "B비번",
    }
    assert wp_credentials("https://blog.cleartone.co.kr", NO_WP, env) == ("A계정", "A비번")
    assert wp_credentials("https://example.com", NO_WP, env) == ("B계정", "B비번")


def test_half_filled_credentials_are_refused():
    # 한쪽만 넣어두면 아이디는 전용, 비번은 공용이 섞여 엉뚱한 계정이 됩니다.
    env = {"WP_USER_CLEARTONE": "전용계정"}

    with pytest.raises(ConfigError) as err:
        wp_credentials("https://blog.cleartone.co.kr", SHARED, env)

    assert "WP_APP_PASSWORD_CLEARTONE" in str(err.value)


def test_missing_credentials_name_the_exact_variables():
    with pytest.raises(ConfigError) as err:
        wp_credentials("https://blog.newclinic.co.kr", NO_WP, {})

    message = str(err.value)
    assert "WP_USER_NEWCLINIC" in message
    assert "WP_APP_PASSWORD_NEWCLINIC" in message


# ------------------------------------------------------------------ 공용 비밀값


def test_only_the_notion_token_is_required():
    secrets = load_secrets({"NOTION_TOKEN": "ntn"})
    assert secrets.notion_token == "ntn"
    assert secrets.wp_user == ""  # 고객사별로 넣을 수 있으므로 없어도 됩니다


def test_missing_notion_token_is_an_error():
    with pytest.raises(ConfigError) as err:
        load_secrets({"WP_USER": "x", "WP_APP_PASSWORD": "y"})
    assert "NOTION_TOKEN" in str(err.value)
