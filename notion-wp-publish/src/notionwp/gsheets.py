"""구글 시트 REST 클라이언트. 값 읽기와 칸 채우기, 딱 두 가지만 합니다.

마스터 시트는 고객사와 함께 보는 문서라 실수로 덮어쓰면 곤란합니다. 그래서 시트 전체를
갈아끼우는 API(`update`/`clear`)는 감싸지 않고, 지정한 칸만 채우는 경로만 열어둡니다.

인증은 서비스 계정 하나로 합니다. 사람 계정을 쓰면 그 사람이 퇴사하거나 비밀번호를
바꿀 때 자동화가 멈추고, 고객사 시트에 토큰을 심어두면 고객사 쪽에서 그 토큰이 보입니다.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TIMEOUT = 30
MAX_RETRIES = 4
#: 액세스 토큰 수명(초). 구글이 허용하는 최대치입니다.
TOKEN_TTL = 3600

#: 환경변수 이름. 서비스 계정 JSON 자체이거나, 그 파일의 경로입니다.
CREDENTIALS_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"


class SheetsError(RuntimeError):
    pass


def _b64url(raw: bytes) -> bytes:
    """JWT 규격의 base64url. 끝의 = 채움 문자는 뺍니다."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def quote_sheet(name: str) -> str:
    """A1 표기법의 탭 이름. '7) 발행 로그' 처럼 공백·괄호가 있으면 따옴표가 필요합니다."""
    if not name:
        return ""
    return "'" + name.replace("'", "''") + "'!"


def a1_column(index: int) -> str:
    """0-기반 열 번호 → A, B, … Z, AA."""
    if index < 0:
        raise ValueError(f"열 번호가 음수입니다: {index}")
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def a1_cell(sheet: str, row: int, col: int) -> str:
    """0-기반 (행, 열) → `'탭 이름'!B4` 꼴의 한 칸 주소."""
    return f"{quote_sheet(sheet)}{a1_column(col)}{row + 1}"


def load_credentials_info(env: dict[str, str] | None = None) -> dict[str, Any]:
    """서비스 계정 JSON을 환경변수에서 읽습니다. 값 자체여도 되고 파일 경로여도 됩니다."""
    src: Any = env if env is not None else os.environ
    raw = (src.get(CREDENTIALS_ENV) or "").strip()

    if not raw:
        raise SheetsError(
            f"환경변수가 비어 있습니다: {CREDENTIALS_ENV}\n"
            f"  구글 서비스 계정 키(JSON)의 내용 또는 그 파일 경로를 넣어 주세요.\n"
            f"  (README '마스터 시트 기록' 항목 참고)"
        )

    if not raw.startswith("{"):
        path = Path(raw).expanduser()
        if not path.is_file():
            raise SheetsError(f"서비스 계정 키 파일을 찾을 수 없습니다: {path}")
        raw = path.read_text(encoding="utf-8")

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SheetsError(f"{CREDENTIALS_ENV} 가 올바른 JSON이 아닙니다: {exc}") from exc

    if not info.get("client_email") or not info.get("private_key"):
        raise SheetsError(
            f"{CREDENTIALS_ENV} 가 서비스 계정 키가 아닙니다 "
            f"(client_email · private_key 가 있어야 합니다)."
        )
    return info


class SheetsClient:
    def __init__(self, info: dict[str, Any], session: requests.Session | None = None):
        self.info = info
        self.session = session or requests.Session()
        self.token_uri = info.get("token_uri") or TOKEN_URI
        #: (액세스 토큰, 만료 시각). 한 번 실행에 여러 고객사를 돌아도 한 번만 받습니다.
        self._credentials: tuple[str, int] | None = None

    @property
    def account_email(self) -> str:
        return self.info.get("client_email", "")

    # ------------------------------------------------------------------ 인증

    def _sign(self, message: bytes) -> bytes:
        # 서비스 계정 인증은 RS256 서명 한 번이면 끝나서, 구글 SDK 대신
        # 이미 깔려 있는 cryptography 로 직접 만듭니다. 의존성이 하나 줄어듭니다.
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:  # pragma: no cover - 설치 안내
            raise SheetsError(
                "cryptography 가 설치되어 있지 않습니다.\n"
                "  pip install -r requirements.txt 를 실행해 주세요."
            ) from exc

        key = serialization.load_pem_private_key(
            self.info["private_key"].encode("utf-8"), password=None
        )
        return key.sign(message, padding.PKCS1v15(), hashes.SHA256())

    def _assertion(self, now: int) -> str:
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": self.info["client_email"],
            "scope": " ".join(SCOPES),
            "aud": self.token_uri,
            "iat": now,
            "exp": now + TOKEN_TTL,
        }
        signing_input = b".".join(_b64url(json.dumps(part).encode()) for part in (header, claims))
        return (signing_input + b"." + _b64url(self._sign(signing_input))).decode("ascii")

    def _token(self) -> str:
        now = int(time.time())
        # 만료 직전에 걸리지 않도록 조금 일찍 갱신합니다.
        if self._credentials and self._credentials[1] > now + 60:
            return self._credentials[0]

        resp = self.session.post(
            self.token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._assertion(now),
            },
            timeout=TIMEOUT,
        )
        if not resp.ok:
            raise SheetsError(
                f"구글 인증에 실패했습니다 ({resp.status_code}). "
                f"서비스 계정 키가 유효한지 확인하세요.\n  {resp.text[:300]}"
            )

        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise SheetsError(f"구글 인증 응답에 access_token 이 없습니다: {str(payload)[:200]}")

        self._credentials = (token, now + int(payload.get("expires_in", TOKEN_TTL)))
        return token

    # ------------------------------------------------------------------ 저수준

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{API_ROOT}{path}"
        delay = 2.0

        for attempt in range(MAX_RETRIES):
            headers = {"Authorization": f"Bearer {self._token()}"}
            try:
                resp = self.session.request(
                    method, url, headers=headers, timeout=TIMEOUT, **kwargs
                )
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES - 1:
                    raise SheetsError(f"구글 시트 요청 실패 {method} {path}: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES - 1:
                    raise SheetsError(
                        f"구글 시트 요청 실패 {method} {path}: "
                        f"{resp.status_code} {resp.text[:300]}"
                    )
                log.warning("구글 시트 %s 재시도 (%.0fs 대기)", resp.status_code, delay)
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code in (403, 404):
                raise SheetsError(
                    f"시트에 접근할 수 없습니다 ({resp.status_code}). "
                    f"스프레드시트를 '{self.account_email}' 에게 편집자로 공유했는지 확인하세요.\n"
                    f"  {resp.text[:300]}"
                )
            if not resp.ok:
                raise SheetsError(
                    f"구글 시트 요청 실패 {method} {path}: {resp.status_code} {resp.text[:500]}"
                )

            return resp.json()

        raise SheetsError(f"구글 시트 요청 실패 {method} {path}: 재시도 소진")

    # ------------------------------------------------------------------ 고수준

    def read(self, spreadsheet_id: str, sheet: str, *, last_column: str = "Z") -> list[list[str]]:
        """탭 전체를 행 배열로 읽습니다. 뒤쪽 빈 칸·빈 행은 잘려서 옵니다."""
        rng = f"{quote_sheet(sheet)}A1:{last_column}"
        data = self._request("GET", f"/{spreadsheet_id}/values/{requests.utils.quote(rng, safe='')}")
        return [[str(c) for c in row] for row in data.get("values", [])]

    def write_cells(self, spreadsheet_id: str, cells: list[tuple[str, str]]) -> int:
        """(A1 주소, 값) 목록을 한 번에 채웁니다. 지정한 칸만 건드립니다."""
        if not cells:
            return 0

        payload = {
            # 날짜는 날짜로, 주소는 링크로 들어가야 사람이 보기 좋습니다.
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": rng, "values": [[value]]} for rng, value in cells],
        }
        data = self._request("POST", f"/{spreadsheet_id}/values:batchUpdate", json=payload)
        return int(data.get("totalUpdatedCells", 0))
