"""고객사 서버가 빠뜨린 중간 인증서를 우리가 들고 다닙니다.

어떤 고객사 서버는 인증서 사슬을 잘못 설치해 둡니다. 예를 들어
www.shesmedi.co.kr 은 중간 인증서(RapidSSL TLS RSA CA G1)를 보내지 않고
그 자리에 최상위 루트를 넣어 보냅니다. 브라우저는 빠진 조각을 알아서
내려받아 메우지만, 서버끼리 통신하는 프로그램은 그러지 않아 검증이 실패합니다.

    SSLCertVerificationError: unable to get local issuer certificate

고객사 호스팅이 고쳐 주면 제일 좋지만, 외부 개발사를 거쳐야 해서 오래 걸리거나
아예 안 되는 곳이 있습니다. 그동안 발행이 멈춰 있을 수는 없으므로, 빠진 중간
인증서를 저장소에 두고 검증할 때 같이 넘깁니다.

    certs/
      RapidSSL-TLS-RSA-CA-G1.pem

**검증을 끄는 것이 아닙니다.** 사슬의 빠진 칸을 채워 줄 뿐이고, 최상위 루트까지
정상적으로 검증됩니다. 신뢰할 수 없는 인증서는 그대로 거부됩니다.

고객사 서버가 제대로 고쳐지면 이 파일이 있어도 아무 영향이 없습니다.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

CERT_DIR = Path(__file__).resolve().parents[2] / "certs"

#: 이 환경이 쓰라고 지정한 CA 번들. 프록시를 쓰는 환경에서는 반드시 이것을
#: 바탕으로 삼아야 합니다 — 무시하고 certifi 만 쓰면 프록시 인증서가 막힙니다.
_BASE_ENV = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE")

_cached: str | None = None
_built = False


def extra_certs(directory: Path | None = None) -> list[Path]:
    root = directory or CERT_DIR
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*.pem") if p.is_file())


def base_bundle(env: dict[str, str] | None = None) -> str | None:
    src = env if env is not None else os.environ
    for name in _BASE_ENV:
        value = (src.get(name) or "").strip()
        if value and Path(value).is_file():
            return value
    try:
        import certifi

        return certifi.where()
    except Exception:  # pragma: no cover - certifi 는 requests 의존성이라 보통 있습니다
        return None


def ca_bundle(directory: Path | None = None, env: dict[str, str] | None = None) -> str | None:
    """검증에 쓸 CA 파일 경로. 보탤 인증서가 없으면 None (기본 동작 그대로).

    한 번 만들어 두고 재사용합니다. 프로세스가 사는 동안만 쓰는 임시 파일입니다.
    """
    global _cached, _built
    if _built and directory is None and env is None:
        return _cached

    extras = extra_certs(directory)
    if not extras:
        if directory is None and env is None:
            _cached, _built = None, True
        return None

    base = base_bundle(env)
    parts: list[str] = []
    if base:
        parts.append(Path(base).read_text(encoding="utf-8", errors="replace"))
    for path in extras:
        parts.append(path.read_text(encoding="utf-8", errors="replace"))

    fd, name = tempfile.mkstemp(prefix="notionwp-ca-", suffix=".pem")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p.strip() + "\n" for p in parts if p.strip()))

    log.info("중간 인증서 %d개를 CA 번들에 보탰습니다: %s",
             len(extras), ", ".join(p.name for p in extras))

    if directory is None and env is None:
        _cached, _built = name, True
    return name
