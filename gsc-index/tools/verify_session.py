"""클라우드에서 Google 세션이 살아 있는지 확인합니다.

    PYTHONPATH=src python3 tools/verify_session.py

GOOGLE_SESSION_B64 환경변수(또는 --state 로 준 파일)를 복원해서 Search Console 에 붙고,
로그인 상태인지 / 속성 목록이 보이는지를 알려줍니다.
아무것도 바꾸지 않습니다. 색인 요청도 하지 않습니다.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from gscindex.browser import browser_context  # noqa: E402

SHOT = pathlib.Path("/tmp/gsc-verify.png")


def load_state(path: str | None):
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    blob = os.environ.get("GOOGLE_SESSION_B64")
    if not blob:
        print("GOOGLE_SESSION_B64 가 비어 있습니다.")
        print("tools/capture_session.py 를 PC 에서 실행해 값을 만든 뒤 환경변수에 넣으세요.")
        return None
    return json.loads(base64.b64decode(blob))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", help="세션 JSON 파일 경로 (환경변수 대신 쓸 때)")
    args = ap.parse_args()

    state = load_state(args.state)
    if state is None:
        return 1

    cookies = state.get("cookies", [])
    print(f"세션 쿠키 {len(cookies)}개 복원")

    with browser_context(storage_state=state) as ctx:
        page = ctx.new_page()
        page.goto("https://search.google.com/search-console",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        url, title = page.url, (page.title() or "")
        page.screenshot(path=str(SHOT))

        print(f"최종 URL : {url[:120]}")
        print(f"제목     : {title[:80]}")
        print(f"스크린샷 : {SHOT}")

        if "/about" in url or "accounts.google.com" in url:
            print()
            print("=> 로그인 안 됨. 세션이 만료됐거나 구글이 재인증을 요구하고 있습니다.")
            print("   PC 에서 capture_session.py 를 다시 돌려 세션을 갱신하세요.")
            return 2

        print()
        print("=> 로그인 유지됨. Search Console 에 접근 가능합니다.")
        body = " ".join(page.inner_text("body")[:400].split())
        print(f"   본문 일부: {body[:200]}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
