"""구글 시트 REST 클라이언트. 값 읽기와 칸 채우기, 딱 두 가지만 합니다.

마스터 시트는 고객사와 함께 보는 문서라 실수로 덮어쓰면 곤란합니다. 그래서 시트 전체를
갈아끼우는 API(`update`/`clear`)는 감싸지 않고, 지정한 칸만 채우는 경로만 열어둡니다.

인증은 서비스 계정 하나로 합니다. 사람 계정을 쓰면 그 사람이 퇴사하거나 비밀번호를
바꿀 때 자동화가 멈추고, 고객사 시트에 토큰을 심어두면 고객사 쪽에서 그 토큰이 보입니다.
"""

from __future__ import annotations

import base64
import hashlib
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



# ------------------------------------------------------------------ RS256 서명

#: SHA-256 DigestInfo 의 고정 앞부분 (RFC 8017 부록 B). 뒤에 해시 32바이트가 붙습니다.
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _der_read(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """DER 한 조각을 읽어 (태그, 값, 다음 위치) 를 돌려줍니다."""
    tag = data[pos]
    length = data[pos + 1]
    pos += 2

    if length & 0x80:  # 길이가 여러 바이트로 적힌 경우
        count = length & 0x7F
        length = int.from_bytes(data[pos : pos + count], "big")
        pos += count

    return tag, data[pos : pos + length], pos + length


def _der_ints(sequence: bytes, count: int) -> list[int]:
    """SEQUENCE 앞쪽의 INTEGER 를 count 개 읽습니다."""
    values, pos = [], 0
    while len(values) < count:
        tag, value, pos = _der_read(sequence, pos)
        if tag != 0x02:  # INTEGER
            raise SheetsError("서비스 계정 키를 읽지 못했습니다 (INTEGER 가 아닙니다).")
        values.append(int.from_bytes(value, "big"))
    return values


def private_numbers(pem: str) -> tuple[int, int]:
    """서비스 계정 키(PEM) → (모듈러스 n, 개인 지수 d).

    구글이 주는 키는 PKCS#8(`BEGIN PRIVATE KEY`) 이고, 그 안에 PKCS#1 키가 들어 있습니다.
    쓰는 값이 n·d 둘뿐이라 DER 을 앞에서부터 필요한 만큼만 읽습니다.
    """
    body = "".join(
        line for line in (pem or "").splitlines() if line and not line.startswith("-----")
    )
    if not body:
        raise SheetsError("서비스 계정 키(private_key)가 PEM 형식이 아닙니다.")

    try:
        der = base64.b64decode(body)
        tag, outer, _ = _der_read(der, 0)
        if tag != 0x30:  # SEQUENCE
            raise SheetsError("서비스 계정 키를 읽지 못했습니다 (SEQUENCE 가 아닙니다).")

        pos = 0
        tag, first, pos = _der_read(outer, pos)
        if tag == 0x02 and first == b"\x00":
            # PKCS#8: 버전 · 알고리즘 다음의 OCTET STRING 안에 PKCS#1 키가 들어 있습니다.
            _, _, pos = _der_read(outer, pos)  # AlgorithmIdentifier
            _, wrapped, _ = _der_read(outer, pos)  # PrivateKey (OCTET STRING)
            _, inner, _ = _der_read(wrapped, 0)  # RSAPrivateKey (SEQUENCE)
        else:
            inner = outer  # PKCS#1 (BEGIN RSA PRIVATE KEY)

        # RSAPrivateKey ::= SEQUENCE { version, modulus(n), publicExponent, privateExponent(d), … }
        _, modulus, _, private_exponent = _der_ints(inner, 4)
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"서비스 계정 키를 읽지 못했습니다: {exc}") from exc

    return modulus, private_exponent


def rs256_sign(pem: str, message: bytes) -> bytes:
    """JWT 용 RS256 서명.

    구글 SDK 없이 표준 라이브러리만으로 만듭니다. 서비스 계정 인증에 필요한 것은
    이 서명 하나뿐이라, 이것 때문에 설치 단계를 늘리지 않으려는 것입니다.
    """
    modulus, private_exponent = private_numbers(pem)
    size = (modulus.bit_length() + 7) // 8

    digest_info = _SHA256_PREFIX + hashlib.sha256(message).digest()
    padding_length = size - len(digest_info) - 3
    if padding_length < 8:
        raise SheetsError("서비스 계정 키가 너무 짧습니다.")

    # EMSA-PKCS1-v1_5: 0x00 0x01 <0xFF 채움> 0x00 <DigestInfo>
    encoded = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), private_exponent, modulus)
    return signature.to_bytes(size, "big")


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
        signature = rs256_sign(self.info["private_key"], signing_input)
        return (signing_input + b"." + _b64url(signature)).decode("ascii")

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
