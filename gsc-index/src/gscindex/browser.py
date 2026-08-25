"""크로미움 기동 — 이 클라우드 환경에 맞춘 설정이 전부 여기 모여 있습니다.

이 환경에서 브라우저를 띄울 때 걸리는 함정이 셋 있고, 셋 다 여기서 처리합니다.
직접 launch() 를 부르지 말고 반드시 이 모듈을 쓰세요.

1) 크로미움 바이너리 경로를 명시해야 합니다.
   pip 로 받은 playwright 가 기대하는 리비전과 이미지에 심긴 크로미움이 달라서,
   그냥 launch() 하면 "playwright install 을 실행하세요" 로 죽습니다.

2) 프록시를 명시해야 합니다.
   HTTPS_PROXY 를 launch(proxy=...) 로 넘기지 않으면 터널이 열리지 않습니다.

3) TLS 1.2 로 상한을 걸어야 합니다.  ← 가장 찾기 어려웠던 부분
   이 세션의 이그레스 게이트웨이는 Google 도메인을 가로채지 않고 그대로 통과시키는데,
   크로미움이 TLS 1.3 으로 붙으면 핸드셰이크가 리셋됩니다(ERR_CONNECTION_RESET).
   curl 은 되고 브라우저만 안 되는 이유가 이것입니다.
   --ssl-version-max=tls1.2 를 주면 정상 동작합니다. 인증서 검증은 그대로 켜둡니다.

CA 등록(scripts/setup-container.sh)이 선행되지 않으면 ERR_CERT_AUTHORITY_INVALID 가 납니다.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# 실제 크롬과 같은 UA. 헤드리스 기본 UA 는 "HeadlessChrome" 이 그대로 노출됩니다.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--ssl-version-max=tls1.2",
    "--disable-blink-features=AutomationControlled",
]


def _proxy() -> dict | None:
    server = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return {"server": server} if server else None


@contextmanager
def browser_context(storage_state=None, headless: bool = True, viewport=(1440, 900)):
    """설정이 끝난 브라우저 컨텍스트를 내줍니다.

    storage_state: playwright storageState (dict 또는 파일 경로). 로그인 세션 복원용.
    """
    from playwright.sync_api import sync_playwright

    if not os.path.exists(CHROME):
        raise RuntimeError(
            f"크로미움을 찾을 수 없습니다: {CHROME}\n"
            "이미지가 바뀌었을 수 있습니다. /opt/pw-browsers 아래를 확인하세요."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME, proxy=_proxy(), headless=headless, args=LAUNCH_ARGS
        )
        ctx = browser.new_context(
            user_agent=USER_AGENT,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": viewport[0], "height": viewport[1]},
            storage_state=storage_state,
        )
        try:
            yield ctx
        finally:
            ctx.close()
            browser.close()
