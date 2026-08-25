"""Google 로그인 세션을 떠서 클라우드로 옮길 수 있는 형태로 뽑아냅니다.

★ 이 스크립트는 클라우드가 아니라 '사용자 PC'에서 실행합니다. ★

    pip install playwright
    python capture_session.py

브라우저 창이 하나 열립니다. growth@lead-gen.team 으로 로그인하고,
Search Console 화면이 정상적으로 보이는 것까지 확인한 뒤 터미널에서 Enter 를 누르세요.

끝나면 두 가지가 나옵니다.
  - google-session.json : 세션 원본 (이 파일은 절대 저장소에 커밋하지 마세요)
  - google-session.b64  : 환경변수에 넣을 한 줄짜리 문자열

b64 파일의 내용을 클라우드 환경 설정의 환경변수 GOOGLE_SESSION_B64 에 넣으면 됩니다.

──────────────────────────────────────────────────────────────────
보안 경고 — 반드시 읽으세요

여기서 뽑히는 것은 growth@lead-gen.team 계정의 로그인 세션 전체입니다.
Search Console 뿐 아니라 Gmail, 드라이브 등 그 계정으로 할 수 있는 모든 것에
접근할 수 있는 열쇠입니다. 비밀번호와 같은 급으로 취급하세요.

  - 저장소에 커밋 금지 (.gitignore 에 이미 넣어두었습니다)
  - 슬랙·메일·메신저로 전달 금지
  - 환경변수로만 주입
  - 자동화를 그만두면 그 계정에서 "모든 기기에서 로그아웃" 을 눌러 폐기
──────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys

OUT_JSON = pathlib.Path("google-session.json")
OUT_B64 = pathlib.Path("google-session.b64")

# 클라우드 쪽과 동일하게 맞춥니다. 어긋나면 구글이 다른 기기로 보고 재인증을 겁니다.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 없습니다.  pip install playwright  를 먼저 실행하세요.")
        return 1

    with sync_playwright() as p:
        try:
            # 이미 깔려 있는 크롬을 씁니다. 별도 브라우저를 내려받지 않습니다.
            browser = p.chromium.launch(channel="chrome", headless=False)
        except Exception:
            print("설치된 크롬을 찾지 못했습니다. 크로미움을 내려받습니다...")
            print("  playwright install chromium  을 실행한 뒤 다시 시도하세요.")
            return 1

        ctx = browser.new_context(
            user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul"
        )
        page = ctx.new_page()
        page.goto("https://accounts.google.com/", wait_until="domcontentloaded")

        print()
        print("=" * 66)
        print(" 열린 브라우저에서 growth@lead-gen.team 으로 로그인하세요.")
        print(" 로그인 후 Search Console 이 보이는 것까지 확인하세요.")
        print(" (스크립트가 자동으로 GSC 를 한 번 열어 쿠키를 모읍니다)")
        print("=" * 66)
        input(" 다 되었으면 Enter: ")

        # GSC 도메인 쿠키까지 확보하려면 실제로 한 번 방문해야 합니다.
        for url in (
            "https://search.google.com/search-console",
            "https://www.google.com/",
        ):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
            except Exception as exc:  # 한 곳 실패해도 나머지는 계속
                print(f"  경고: {url} 방문 실패 ({exc.__class__.__name__})")

        if "/about" in page.url:
            print()
            print(" ! Search Console 이 로그인 안 된 소개 페이지로 보입니다.")
            print(" ! 로그인이 안 끝났을 수 있습니다. 확인하고 다시 실행하세요.")

        state = ctx.storage_state()
        browser.close()

    OUT_JSON.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    blob = base64.b64encode(json.dumps(state).encode()).decode()
    OUT_B64.write_text(blob, encoding="utf-8")

    google_cookies = [c for c in state.get("cookies", []) if "google" in c.get("domain", "")]
    print()
    print(f" 저장 완료: {OUT_JSON}  (쿠키 {len(state.get('cookies', []))}개, "
          f"그중 google 도메인 {len(google_cookies)}개)")
    print(f" 환경변수용 문자열: {OUT_B64}  ({len(blob):,} 자)")
    print()
    print(" 다음 단계 — 아래 값을 클라우드 환경의 GOOGLE_SESSION_B64 에 넣으세요.")
    print(" 이 두 파일은 넣고 나면 지우는 편이 안전합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
