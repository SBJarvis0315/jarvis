"""소하 AI(soha-ai.com) 브라우저 드라이버.

API 를 쓰지 않습니다. 팀원이 손으로 하던 것과 같은 순서로 브라우저를 몹니다.

    로그인 → 개요(메인 대시보드) 캡쳐 → 브랜드 대시보드 캡쳐 →
    프롬프트/브랜드/데이터소스 탭 CSV 내려받기

화면 구조는 `profiles/soha.json` 이 압니다. 프로파일이 비어 있으면 이 모듈은
**아무것도 수집하지 않고** `--inspect` 만 할 수 있습니다. 실제 화면을 보기 전에
지어낸 선택자를 넣지 않기 위한 것입니다 (`inspect/NOTES.md` 참고).
"""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

LOGIN_URL = "https://www.soha-ai.com/login"

PROFILE_PATH = Path(__file__).with_name("profiles") / "soha.json"


class SohaError(RuntimeError):
    pass


def find_chromium() -> str:
    """환경에 이미 있는 Chromium 을 씁니다. 내려받지 않습니다."""

    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    patterns = (
        "chromium-*/chrome-linux/chrome",
        "chromium_headless_shell-*/chrome-linux/headless_shell",
    )
    for pattern in patterns:
        for path in sorted(root.glob(pattern), reverse=True):
            if path.exists():
                return str(path)
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = _which(name)
        if found:
            return found
    raise SohaError("Chromium 을 찾지 못했습니다. PLAYWRIGHT_BROWSERS_PATH 를 확인하세요.")


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def chromium_args() -> list[str]:
    """브라우저 실행 인자.

    루틴이 도는 원격 환경의 이그레스 프록시는 TLS 1.3 핸드셰이크를 끊습니다. curl 은
    1.2 로 알아서 내려가지만 Chromium 은 내려가지 않아 사이트에 아예 닿지 못합니다
    (`--board-inspect` 에서 같은 문제를 겪었습니다). 프록시 뒤에 있을 때만 1.2 로
    고정합니다. `SOHA_CHROMIUM_ARGS` 로 더 붙일 수 있습니다.
    """

    args = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        args.append("--ssl-version-max=tls1.2")
    args.extend(shlex.split(os.environ.get("SOHA_CHROMIUM_ARGS", "")))
    return args


@dataclass
class Credentials:
    """고객사별 소하 계정.

    환경변수를 먼저 봅니다. 예: `SOHA_USER_CHAMPODONAMU`,
    `SOHA_PASSWORD_CHAMPODONAMU`. 없으면 호출자가 넘긴 값을 씁니다
    (리포트 템플릿의 'AEO/GEO 트래킹 대시보드' 콜아웃에 적혀 있습니다).
    """

    user: str
    password: str

    @classmethod
    def resolve(cls, slug: str, user: str = "", password: str = "") -> "Credentials":
        key = re.sub(r"[^A-Z0-9]", "_", slug.upper())
        user = os.environ.get(f"SOHA_USER_{key}", "") or user
        password = os.environ.get(f"SOHA_PASSWORD_{key}", "") or password
        if not user or not password:
            raise SohaError(
                f"{slug} 의 소하 계정이 없습니다. SOHA_USER_{key}/SOHA_PASSWORD_{key} 를"
                " 넣거나 --soha-user/--soha-password 로 넘기세요."
            )
        return cls(user, password)


@dataclass
class Profile:
    """화면 구조. 정찰로 채웁니다."""

    login: dict[str, str] = field(default_factory=dict)
    dashboard: dict[str, Any] = field(default_factory=dict)
    downloads: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return bool(self.login.get("user") and self.login.get("password"))

    @classmethod
    def load(cls, path: Path = PROFILE_PATH) -> "Profile":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            login=data.get("login", {}),
            dashboard=data.get("dashboard", {}),
            downloads=data.get("downloads", {}),
        )


class Browser:
    """Playwright 컨텍스트 하나를 감쌉니다."""

    def __init__(self, headless: bool = True, downloads: Path | None = None) -> None:
        self.headless = headless
        self.downloads = downloads
        self._pw: Any = None
        self._browser: Any = None
        self.page: Any = None

    def __enter__(self) -> "Browser":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 환경 문제
            raise SohaError(
                "playwright 가 없습니다. `pip install playwright` 후 다시 실행하세요."
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            executable_path=find_chromium(), headless=self.headless, args=chromium_args()
        )
        context = self._browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="ko-KR",
            accept_downloads=True,
        )
        self.page = context.new_page()
        return self

    def __exit__(self, *exc: object) -> None:
        for close in (self._browser, self._pw):
            try:
                if close is self._pw:
                    close.stop()
                elif close:
                    close.close()
            except Exception:  # pragma: no cover - 정리 중 오류는 삼킵니다
                pass


def login(browser: Browser, creds: Credentials, profile: Profile) -> None:
    """로그인. 프로파일이 있으면 그 선택자를, 없으면 흔한 모양을 시도합니다."""

    page = browser.page
    page.goto(profile.login.get("url", LOGIN_URL), wait_until="domcontentloaded")

    user_sel = profile.login.get("user") or (
        "input[type=email], input[name*=email i], input[name*=id i]"
    )
    pass_sel = profile.login.get("password") or "input[type=password]"
    submit_sel = profile.login.get("submit") or "button[type=submit]"

    page.fill(user_sel, creds.user)
    page.fill(pass_sel, creds.password)
    page.click(submit_sel)
    page.wait_for_load_state("networkidle")

    if "/login" in page.url:
        raise SohaError(f"로그인에 실패한 것으로 보입니다. 현재 주소: {page.url}")


def inspect(out_dir: Path, creds: Credentials, headless: bool = True) -> Path:
    """정찰. 로그인 후 화면을 통째로 떠서 `out_dir` 에 남깁니다.

    발행도, 수집도 하지 않습니다. 이 결과를 보고 `profiles/soha.json` 을 채웁니다.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    notes: dict[str, Any] = {"stamp": stamp, "steps": []}

    with Browser(headless=headless, downloads=out_dir) as browser:
        page = browser.page
        profile = Profile.load()

        page.goto(profile.login.get("url", LOGIN_URL), wait_until="domcontentloaded")
        _dump(page, out_dir, f"{stamp}-01-login", notes)

        try:
            login(browser, creds, profile)
            notes["login"] = "ok"
        except Exception as exc:
            notes["login"] = f"실패: {exc}"
            _dump(page, out_dir, f"{stamp}-02-login-failed", notes)
            (out_dir / "inspect.json").write_text(
                json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return out_dir

        _dump(page, out_dir, f"{stamp}-03-landing", notes)
        notes["landing_url"] = page.url
        notes["nav"] = _collect(page, "a, [role=tab], button")
        notes["download_candidates"] = [
            item
            for item in notes["nav"]
            if re.search(r"csv|다운로드|내보내기|export", item.get("text", ""), re.I)
        ]

    (out_dir / "inspect.json").write_text(
        json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_dir


def _dump(page: Any, out_dir: Path, name: str, notes: dict[str, Any]) -> None:
    png = out_dir / f"{name}.png"
    html = out_dir / f"{name}.html"
    page.screenshot(path=str(png), full_page=True)
    html.write_text(page.content(), encoding="utf-8")
    notes["steps"].append({"name": name, "url": page.url, "png": png.name, "html": html.name})


def _collect(page: Any, selector: str, limit: int = 200) -> list[dict[str, str]]:
    script = """
    (sel) => Array.from(document.querySelectorAll(sel)).slice(0, 200).map((el) => ({
        tag: el.tagName.toLowerCase(),
        text: (el.innerText || '').trim().slice(0, 60),
        href: el.getAttribute('href') || '',
        testid: el.getAttribute('data-testid') || '',
        cls: (el.getAttribute('class') || '').slice(0, 80),
    })).filter((item) => item.text || item.href)
    """
    items = page.evaluate(script, selector)
    return items[:limit]
