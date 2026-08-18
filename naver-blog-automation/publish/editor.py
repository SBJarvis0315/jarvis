#!/usr/bin/env python3
"""네이버 스마트에디터 조작. 사용자 PC에서 실행한다.

네이버는 데이터센터 IP의 로그인을 막기 때문에 클라우드 환경에서는 돌지 않는다.
로그인은 한 번 사람이 직접 하고, 그 세션을 브라우저 프로필에 남겨 재사용한다.

  python3 editor.py login                     # 최초 1회. 창이 열리면 직접 로그인
  python3 editor.py inspect --blog niceolive  # 에디터 구조를 떠서 JSON 으로 저장
  python3 editor.py publish --plan work/plan.json --assign work/assign.json

publish 는 selectors.json 이 채워진 뒤에 동작한다. inspect 결과를 보고 채운다.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, "..", "work", "browser-profile")
SELECTORS = os.path.join(HERE, "selectors.json")
WRITE_URL = "https://blog.naver.com/{blog}?Redirect=Write"
LOGIN_URL = "https://nid.naver.com/nidlogin.login"


def need_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        print("playwright 가 설치되어 있지 않습니다.\n"
              "  pip install playwright\n"
              "  python -m playwright install chromium", file=sys.stderr)
        return False


def browser(pw, headless=False):
    os.makedirs(PROFILE, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        PROFILE,
        headless=headless,
        viewport={"width": 1440, "height": 960},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        args=["--disable-blink-features=AutomationControlled"],
    )


def cmd_login(args):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = browser(pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("창이 열렸습니다. 네이버에 직접 로그인해 주세요.")
        print("로그인이 끝나면 이 터미널에서 엔터를 눌러주세요.")
        input()
        page.goto("https://blog.naver.com/", wait_until="domcontentloaded")
        time.sleep(2)
        logged = page.locator("a:has-text('로그아웃'), .log_out, #gnb_logout_button").count() > 0
        print("로그인 상태로 보입니다." if logged
              else "로그인 여부를 확인하지 못했습니다. 창에서 직접 확인해 주세요.")
        print("프로필 저장 위치: %s" % os.path.abspath(PROFILE))
        ctx.close()
    return 0


def dump_frame(frame):
    """에디터 프레임 안에서 셀렉터 후보가 될 만한 것들을 훑는다."""
    js = """
    () => {
      const pick = (el) => ({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.baseVal !== undefined
              ? el.className.baseVal : el.className || '').toString().slice(0, 160),
        id: el.id || null,
        role: el.getAttribute('role'),
        aria: el.getAttribute('aria-label'),
        title: el.getAttribute('title'),
        dataName: el.getAttribute('data-name'),
        dataLog: el.getAttribute('data-log'),
        text: (el.innerText || '').trim().slice(0, 40)
      });
      const q = (sel) => Array.from(document.querySelectorAll(sel));
      return {
        url: location.href,
        title: document.title,
        buttons: q('button, a[role=button], .se-toolbar-item, [class*=toolbar] button')
                   .slice(0, 200).map(pick),
        editable: q('[contenteditable=true]').slice(0, 20).map(pick),
        components: Array.from(new Set(
          q('[class*="se-component"]').slice(0, 200)
            .map(e => (e.className || '').toString().slice(0, 90)))),
        panels: q('[class*=template], [class*=Template]').slice(0, 60).map(pick),
        iframes: q('iframe').map(f => ({name: f.name, src: (f.src || '').slice(0, 120)}))
      };
    }
    """
    try:
        return frame.evaluate(js)
    except Exception as e:
        return {"error": str(e)}


def cmd_inspect(args):
    from playwright.sync_api import sync_playwright
    out = {"captured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "frames": []}
    with sync_playwright() as pw:
        ctx = browser(pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(WRITE_URL.format(blog=args.blog), wait_until="domcontentloaded")
        print("글쓰기 화면을 여는 중입니다. 로딩이 끝나면 엔터를 눌러주세요.")
        print("템플릿 패널을 열어 '내 템플릿' 까지 띄워두시면 그 구조까지 함께 뜹니다.")
        input()

        for fr in page.frames:
            info = dump_frame(fr)
            info["frame_name"] = fr.name
            info["frame_url"] = fr.url[:160]
            out["frames"].append(info)

        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        shot = os.path.splitext(args.out)[0] + ".png"
        try:
            page.screenshot(path=shot, full_page=False)
        except Exception:
            shot = None
        ctx.close()

    print("프레임 %d개 기록 → %s" % (len(out["frames"]), args.out))
    for fr in out["frames"]:
        n = len(fr.get("buttons", []) or [])
        e = len(fr.get("editable", []) or [])
        print("  %-16s 버튼 %3d · 편집영역 %d · %s"
              % (fr["frame_name"] or "(main)", n, e, fr["frame_url"][:70]))
    if shot:
        print("스크린샷: %s" % shot)
    print("\n이 파일과 스크린샷을 채팅에 올려주시면 selectors.json 을 채워 드립니다.")
    return 0


def load_selectors():
    with open(SELECTORS, encoding="utf-8") as f:
        sel = json.load(f)
    todo = [k for k, v in sel.items() if isinstance(v, str) and v.startswith("TODO")]
    return sel, todo


def cmd_publish(args):
    sel, todo = load_selectors()
    if todo:
        print("selectors.json 이 아직 비어 있습니다: %s" % ", ".join(todo), file=sys.stderr)
        print("먼저 `editor.py inspect` 결과를 공유해 주세요.", file=sys.stderr)
        return 2
    print("selectors.json 이 채워졌습니다. 발행 단계는 그 값에 맞춰 구현합니다.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="네이버 로그인 세션을 프로필에 남긴다")

    i = sub.add_parser("inspect", help="에디터 구조를 떠서 저장")
    i.add_argument("--blog", required=True, help="블로그 아이디 (예: niceolive)")
    i.add_argument("--out", default=os.path.join(HERE, "..", "work", "inspect.json"))

    p = sub.add_parser("publish", help="plan 대로 임시저장까지 작성")
    p.add_argument("--plan", required=True)
    p.add_argument("--assign", required=True)

    args = ap.parse_args()
    if not need_playwright():
        return 1
    return {"login": cmd_login, "inspect": cmd_inspect, "publish": cmd_publish}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
