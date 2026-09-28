# -*- coding: utf-8 -*-
"""고객사 서버가 빠뜨린 중간 인증서를 우리가 보태는 동작.

검증을 끄는 것이 아니라 사슬의 빈 칸을 채우는 것입니다. 보탤 것이 없으면
아무것도 하지 않아야 하고, 이 환경이 지정한 CA 번들은 반드시 바탕에 깔려야
합니다 — 무시하면 프록시를 쓰는 환경에서 모든 요청이 막힙니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from notionwp.trust import base_bundle, ca_bundle, extra_certs

LEAF = "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----"
EXTRA = "-----BEGIN CERTIFICATE-----\nZXh0cmE=\n-----END CERTIFICATE-----"


def test_nothing_to_add_means_default_behaviour(tmp_path):
    assert extra_certs(tmp_path) == []
    assert ca_bundle(tmp_path, env={}) is None


def test_the_environment_bundle_is_the_base(tmp_path):
    """프록시를 쓰는 환경이 지정한 번들을 무시하면 모든 요청이 막힙니다."""
    base = tmp_path / "base.pem"
    base.write_text(LEAF, encoding="utf-8")
    assert base_bundle({"REQUESTS_CA_BUNDLE": str(base)}) == str(base)


def test_extras_are_appended_to_the_environment_bundle(tmp_path):
    base = tmp_path / "base.pem"
    base.write_text(LEAF, encoding="utf-8")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "RapidSSL.pem").write_text(EXTRA, encoding="utf-8")

    out = ca_bundle(certs, env={"REQUESTS_CA_BUNDLE": str(base)})

    assert out is not None
    text = Path(out).read_text(encoding="utf-8")
    assert "ZmFrZQ==" in text, "환경 번들이 빠지면 안 됩니다"
    assert "ZXh0cmE=" in text, "보탠 중간 인증서가 들어가야 합니다"


def test_only_pem_files_are_picked_up(tmp_path):
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "쓰는것.pem").write_text(EXTRA, encoding="utf-8")
    (certs / "README.md").write_text("설명", encoding="utf-8")
    (certs / "안쓰는것.crt").write_text(EXTRA, encoding="utf-8")

    assert [p.name for p in extra_certs(certs)] == ["쓰는것.pem"]
