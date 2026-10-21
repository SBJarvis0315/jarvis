"""모든 테스트에 공통으로 적용되는 준비."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import sys
from pathlib import Path

# 패키지를 설치하지 않아도 테스트가 돌도록 src 를 경로에 넣습니다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notionwp import authors as real_authors
from notionwp import publish as publish_mod


@pytest.fixture(autouse=True)
def _default_author(monkeypatch):
    """발행 테스트의 고객사에 작성자 파일이 없어도 돌게 합니다.

    작성자 규칙 자체는 test_authors.py 가 `notionwp.authors` 를 직접 불러 검증합니다.
    """
    monkeypatch.setattr(
        publish_mod,
        "authors_mod",
        SimpleNamespace(
            load=lambda client, directory=None: real_authors.Author(client, "테스트 저자"),
            resolve=real_authors.resolve,
        ),
    )
