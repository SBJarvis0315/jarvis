"""자체 홈페이지 게시판 드라이버 — 브라우저로 관리자 화면을 사람처럼 조작합니다.

워드프레스에는 REST API 가 있지만 병원 홈페이지 제작사가 만든 관리자 화면에는
그런 것이 없습니다. 있는 것은 로그인 폼, 글쓰기 폼, 에디터의 이미지 버튼뿐입니다.
그래서 팀원이 손으로 하던 일을 그대로 브라우저(Playwright + Chromium)가 합니다.

    로그인 → 게시판관리 > 블로그 → 글쓰기 → 이미지 업로드 → </> 코드 보기에
    HTML 붙이기 → 조회수·제목 채우기 → 등록 → 목록에서 글 번호 확인

사이트마다 폼이 조금씩 다르므로 그 차이는 `boards/<호스트>.json` 프로파일에
둡니다. 프로파일이 없는 사이트는 `--board-inspect` 로 화면을 떠서 보고 사람이나
에이전트가 한 번 만들어 굳힙니다 — 썸네일 디자인과 같은 방식입니다.

실패하면 그 순간의 스크린샷과 HTML 을 작업 폴더에 남깁니다. 브라우저 자동화는
어디서 걸렸는지 눈으로 봐야 고칠 수 있습니다.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .thumbnail import find_chromium

log = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parents[2] / "boards"

NAV_TIMEOUT_MS = 45_000
#: 이미지 업로드는 서버가 받아 저장하고 에디터에 <img> 를 꽂는 시간이 붙습니다.
UPLOAD_TIMEOUT_MS = 90_000
POLL_S = 0.5


class BoardError(RuntimeError):
    pass


# ---------------------------------------------------------------- 프로파일


@dataclass
class BoardProfile:
    """사이트 하나의 관리자 화면 생김새. `boards/<호스트>.json` 에 굳혀 둡니다."""

    host: str
    #: 관리자 목록 화면. 설정표의 '게시판 주소'가 있으면 그 값이 우선입니다.
    admin_url: str = ""
    #: 로그인 화면. 비우면 admin_url 이 로그인으로 돌려보내는 것을 그대로 씁니다.
    login_url: str = ""
    #: 공개 글 주소. {id} 자리에 글 번호가 들어갑니다.
    public_url: str = ""
    #: 목록 화면에서 눌러야 하는 게시판 탭의 글자 (예: 블로그). 비우면 누르지 않습니다.
    tab: str = ""
    write_button: str = "글쓰기"
    #: 등록 버튼 후보. 앞에서부터 찾아 처음 보이는 것을 누릅니다.
    submit_buttons: list[str] = field(default_factory=lambda: ["등록", "저장", "확인", "완료"])
    #: 목록의 글 링크에서 글 번호를 읽어낼 쿼리 파라미터 이름.
    id_param: str = "id"
    #: 글쓰기 폼의 행 머리글. 이 글자가 있는 행에서 입력칸을 찾습니다.
    labels: dict[str, str] = field(
        default_factory=lambda: {"title": "제목", "hit": "조회수", "content": "내용", "html": "HTML"}
    )
    #: 'HTML' 라디오 중 골라야 하는 항목의 글자.
    html_mode: str = "HTML"
    #: 조회수 칸에 넣을 임의의 값 범위. 팀이 손으로 올릴 때 쓰던 관행입니다.
    hit_min: int = 500
    hit_max: int = 1100
    note: str = ""

    @classmethod
    def load(cls, admin_url: str, directory: Path | None = None) -> BoardProfile:
        host = urlparse(admin_url).netloc.lower()
        if not host:
            raise BoardError(f"게시판 주소가 올바르지 않습니다: {admin_url!r}")

        # www 가 있든 없든 같은 사이트입니다. 설정표에 어느 쪽으로 적혀도 찾습니다.
        root = directory or PROFILES_DIR
        alternates = [host, host.removeprefix("www."), f"www.{host.removeprefix('www.')}"]
        path = next((root / f"{h}.json" for h in dict.fromkeys(alternates) if (root / f"{h}.json").exists()),
                    root / f"{host}.json")
        if not path.exists():
            raise BoardError(
                f"'{host}' 게시판 프로파일이 없습니다 ({path}).\n"
                f"  `--board-inspect` 로 관리자 화면을 떠서 확인한 뒤 프로파일을 만들어 주세요. "
                f"(boards/ 의 다른 파일을 참고)"
            )

        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.setdefault("host", host)
        profile = cls(**raw)
        if admin_url:
            profile.admin_url = admin_url
        return profile

    def save(self, directory: Path | None = None) -> Path:
        directory = directory or PROFILES_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.host}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def public_link(self, post_id: str) -> str:
        if not self.public_url or not post_id:
            return ""
        return self.public_url.replace("{id}", str(post_id))


@dataclass
class BoardPost:
    id: str
    title: str
    link: str = ""


# ------------------------------------------------------------------ 드라이버


class BoardClient:
    """관리자 화면 하나에 로그인해 글을 올립니다. `with` 로 감싸 쓰세요."""

    def __init__(
        self,
        profile: BoardProfile,
        user: str,
        password: str,
        *,
        artifacts: Path | None = None,
        headless: bool = True,
    ):
        self.profile = profile
        self.user = user
        self.password = password
        self.artifacts = artifacts
        self.headless = headless
        self.dialogs: list[str] = []
        self._pw: Any = None
        self._browser: Any = None
        self.page: Any = None

    # ----------------------------------------------------------- 수명

    def __enter__(self) -> BoardClient:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 환경 문제
            raise BoardError(
                "playwright 가 설치되어 있지 않습니다. `pip install playwright` 후 다시 실행하세요."
            ) from exc

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            executable_path=find_chromium(), headless=self.headless
        )
        context = self._browser.new_context(
            viewport={"width": 1400, "height": 1000},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        self.page = context.new_page()
        self.page.set_default_timeout(NAV_TIMEOUT_MS)
        # '등록되었습니다' 같은 alert 가 뜨면 사람처럼 확인을 누르고, 내용은 남겨 둡니다.
        self.page.on("dialog", self._on_dialog)
        return self

    def __exit__(self, *exc: object) -> None:
        for closer in (
            lambda: self._browser.close() if self._browser else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                closer()
            except Exception:  # 닫다가 난 오류는 결과를 바꾸지 않습니다.
                pass

    def _on_dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        log.info("브라우저 알림: %s", dialog.message)
        dialog.accept()

    # ----------------------------------------------------------- 진단

    def snapshot(self, step: str) -> str:
        """지금 화면을 파일로 남기고 그 경로를 돌려줍니다. 실패 원인 추적용입니다."""
        if not self.artifacts or self.page is None:
            return ""
        try:
            self.artifacts.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            base = self.artifacts / f"{stamp}-{step}"
            self.page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
            base.with_suffix(".html").write_text(self.page.content(), encoding="utf-8")
            return str(base.with_suffix(".png"))
        except Exception as exc:
            log.debug("화면을 남기지 못했습니다: %s", exc)
            return ""

    def _fail(self, message: str, step: str) -> BoardError:
        shot = self.snapshot(step)
        tail = f" (화면: {shot})" if shot else ""
        if self.dialogs:
            tail += f" · 브라우저 알림: {' / '.join(self.dialogs[-3:])}"
        return BoardError(f"{message}{tail}")

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            # 광고·통계 스크립트가 계속 통신하는 사이트도 있습니다. 로드는 끝난 것으로 봅니다.
            self.page.wait_for_load_state("domcontentloaded")

    # ----------------------------------------------------------- 로그인

    def login(self) -> None:
        page = self.page
        page.goto(self.profile.login_url or self.profile.admin_url)
        self._settle()

        password = page.locator("input[type=password]")
        if password.count() == 0:
            if self._looks_logged_in():
                return
            raise self._fail("로그인 화면도, 관리자 화면도 아닙니다. 주소를 확인해 주세요", "login")

        password = password.first
        # 아이디 칸은 비밀번호 칸과 같은 폼 안에서 그 앞에 있는 글자 입력칸입니다.
        form = password.locator("xpath=ancestor::form[1]")
        scope = form if form.count() else page
        user_box = scope.locator(
            "input:not([type]), input[type=text], input[type=email], input[type=tel]"
        ).first
        if user_box.count() == 0:
            raise self._fail("로그인 폼에서 아이디 칸을 찾지 못했습니다", "login")

        user_box.fill(self.user)
        password.fill(self.password)
        password.press("Enter")
        self._settle()

        if page.locator("input[type=password]").count() and not self._looks_logged_in():
            # 엔터로 제출되지 않는 폼도 있습니다 (버튼이 스크립트로만 동작하는 경우).
            # 그때는 사람처럼 '로그인' 버튼을 직접 누릅니다.
            button = self._login_button(scope)
            if button is not None:
                button.click()
                self._settle()

        if page.locator("input[type=password]").count() and not self._looks_logged_in():
            raise self._fail("로그인에 실패했습니다. 아이디·비밀번호를 확인해 주세요", "login-failed")
        log.info("관리자 로그인 완료: %s", self.profile.host)

    def _login_button(self, scope: Any) -> Any:
        for selector in (
            "input[type=submit]",
            "button[type=submit]",
            "button:has-text('로그인')",
            "a:has-text('로그인')",
            "input[value*='로그인']",
            "button:has-text('LOGIN')",
        ):
            found = scope.locator(selector)
            if found.count():
                return found.first
        return None

    def _looks_logged_in(self) -> bool:
        page = self.page
        for text in ("LOG OUT", "LOGOUT", "로그아웃", self.profile.write_button):
            if page.get_by_text(text, exact=False).count():
                return True
        return False

    # ----------------------------------------------------------- 목록

    def open_list(self) -> None:
        page = self.page
        page.goto(self.profile.admin_url)
        self._settle()

        tab = self.profile.tab
        if tab:
            candidates = page.get_by_role("link", name=tab, exact=True)
            if candidates.count() == 0:
                candidates = page.get_by_text(tab, exact=True)
            if candidates.count():
                candidates.first.click()
                self._settle()

    def find_post(self, title: str) -> BoardPost | None:
        """목록에서 같은 제목의 글을 찾습니다. 없으면 None.

        같은 원고를 두 번 올리지 않기 위한 유일한 장치입니다. 워드프레스처럼 노션
        ID 를 글에 각인할 곳이 없으므로 제목이 열쇠입니다.
        """
        self.open_list()
        page = self.page
        wanted = _norm(title)

        # 검색칸이 있으면 첫 페이지 밖의 글도 찾을 수 있게 제목으로 검색합니다.
        search = page.locator(
            "input[name*=keyword], input[name*=search], input[name=key], input[type=search]"
        )
        if search.count():
            try:
                search.first.fill(title)
                search.first.press("Enter")
                self._settle()
            except Exception as exc:
                log.debug("목록 검색을 건너뜁니다: %s", exc)
                self.open_list()

        for link in page.locator("a").all():
            try:
                if _norm(link.inner_text()) != wanted:
                    continue
            except Exception:
                continue
            row = link.locator("xpath=ancestor::tr[1]")
            post_id = self._post_id_from(row if row.count() else link)
            return BoardPost(id=post_id, title=title, link=self.profile.public_link(post_id))
        return None

    def _post_id_from(self, scope: Any) -> str:
        pattern = re.compile(rf"[?&]{re.escape(self.profile.id_param)}=(\d+)")
        for attr in ("href", "onclick", "action", "data-id"):
            for value in scope.locator(f"[{attr}]").evaluate_all(
                f"els => els.map(e => e.getAttribute('{attr}'))"
            ):
                match = pattern.search(value or "")
                if match:
                    return match.group(1)
        return ""

    # ----------------------------------------------------------- 글쓰기 폼

    def open_write_form(self) -> None:
        self.open_list()
        page = self.page
        label = self.profile.write_button

        button = page.get_by_role("link", name=label, exact=True)
        if button.count() == 0:
            button = page.get_by_role("button", name=label, exact=True)
        if button.count() == 0:
            button = page.locator(f"input[value='{label}']")
        if button.count() == 0:
            button = page.get_by_text(label, exact=True)
        if button.count() == 0:
            raise self._fail(f"목록 화면에서 '{label}' 버튼을 찾지 못했습니다", "list")

        button.first.click()
        self._settle()

        if self._field("title").count() == 0:
            raise self._fail("글쓰기 폼에서 제목 칸을 찾지 못했습니다", "write-form")

    def _row(self, label: str) -> Any:
        """행 머리글이 `label` 인 표 행. 관리자 화면은 거의 다 <table> 로 짜여 있습니다."""
        quoted = json.dumps(label, ensure_ascii=False)
        return self.page.locator(f"xpath=//tr[normalize-space(*[1])={quoted}]")

    def _field(self, key: str) -> Any:
        label = self.profile.labels.get(key, "")
        row = self._row(label) if label else None
        if row is not None and row.count():
            return row.first.locator("input:not([type=hidden]):not([type=radio]), textarea").first
        # 표가 아닌 폼에 대비한 폴백. name 에 흔히 쓰는 이름이 들어 있으면 그것을 씁니다.
        names = {
            "title": "input[name*=subject], input[name*=title], input[name*=subj]",
            "hit": "input[name*=hit], input[name*=view], input[name*=count]",
        }
        selector = names.get(key)
        return self.page.locator(selector) if selector else self.page.locator("__none__")

    def fill_title(self, title: str) -> None:
        box = self._field("title")
        if box.count() == 0:
            raise self._fail("제목 칸을 찾지 못했습니다", "write-form")
        box.fill(title)

    def fill_hit(self, hit: int) -> None:
        box = self._field("hit")
        if box.count() == 0:
            log.info("조회수 칸이 없어 건너뜁니다")
            return
        box.fill(str(hit))

    def ensure_html_mode(self) -> None:
        """'HTML / HTML+BR / 텍스트' 중 HTML 을 고릅니다. 코드로 붙이는 글이니까요."""
        label = self.profile.labels.get("html", "")
        row = self._row(label) if label else None
        if row is None or row.count() == 0:
            return
        radios = row.first.locator("input[type=radio]")
        if radios.count() == 0:
            return

        wanted = _norm(self.profile.html_mode)
        for radio in radios.all():
            text = ""
            try:
                text = radio.evaluate(
                    "el => (el.closest('label') || el.parentElement || {}).innerText "
                    "|| (el.nextSibling && el.nextSibling.textContent) || ''"
                )
            except Exception:
                pass
            # 'HTML' 은 'HTML+BR' 의 앞부분이기도 하므로, 각 라디오 바로 뒤 글자만 봅니다.
            first_word = _norm(text).split(" ")[0] if text else ""
            if first_word == wanted:
                radio.check()
                return
        radios.first.check()

    # ----------------------------------------------------------- 이미지

    def upload_image(self, data: bytes, filename: str) -> str:
        """에디터의 이미지 버튼으로 파일을 올리고 서버가 준 주소를 돌려줍니다.

        올라간 <img> 는 곧바로 본문에서 걷어냅니다. 최종 본문은 우리가 만든 HTML 로
        통째로 갈아 끼우고, 이미지 주소만 그 안에 씁니다.
        """
        page = self.page
        editable = page.locator(".note-editable").first
        if editable.count() == 0:
            raise self._fail("에디터(.note-editable)를 찾지 못했습니다. 프로파일을 확인해 주세요", "editor")

        before = editable.locator("img").count()
        self._open_image_dialog()

        file_input = page.locator(
            ".note-image-input, .note-modal input[type=file], .modal input[type=file], input[type=file]"
        ).first
        if file_input.count() == 0:
            raise self._fail("이미지 올리기 칸(input[type=file])을 찾지 못했습니다", "image-dialog")

        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        file_input.set_input_files({"name": filename, "mimeType": mime, "buffer": data})

        deadline = time.monotonic() + UPLOAD_TIMEOUT_MS / 1000
        src = ""
        while time.monotonic() < deadline:
            images = editable.locator("img")
            if images.count() > before:
                src = images.nth(images.count() - 1).get_attribute("src") or ""
                if src and not src.startswith(("data:", "blob:")):
                    break
            time.sleep(POLL_S)

        if not src:
            raise self._fail(f"이미지가 에디터에 들어오지 않았습니다: {filename}", "image-upload")
        if src.startswith(("data:", "blob:")):
            raise self._fail(
                "에디터가 이미지를 서버에 올리지 않고 본문에 통째로 박아 넣습니다. "
                "이 상태로 올리면 글이 수 MB 가 됩니다",
                "image-inline",
            )

        # 방금 들어온 이미지는 걷어냅니다. 최종 본문에서 주소만 씁니다.
        editable.locator("img").nth(before).evaluate("el => el.remove()")
        self._close_dialog()

        url = urljoin(page.url, src)
        log.debug("이미지 업로드: %s → %s", filename, url)
        return url

    def _open_image_dialog(self) -> None:
        page = self.page
        for selector in (
            "button[data-event=showImageDialog]",
            ".note-toolbar button:has(.note-icon-picture)",
            "button[aria-label*=Picture]",
            "button[aria-label*=이미지]",
            ".note-toolbar button:has-text('이미지')",
        ):
            button = page.locator(selector)
            if button.count():
                button.first.click()
                page.wait_for_timeout(300)
                return
        raise self._fail("에디터의 이미지 버튼을 찾지 못했습니다", "image-button")

    def _close_dialog(self) -> None:
        page = self.page
        close = page.locator(
            ".note-modal.open .close, .modal.in .close, .note-modal.open [aria-label=Close]"
        )
        if close.count():
            try:
                close.first.click()
                return
            except Exception:
                pass
        page.keyboard.press("Escape")

    # ----------------------------------------------------------- 본문

    def set_content(self, content: str) -> None:
        """본문 HTML 을 에디터에 통째로 넣습니다. 세 가지 길을 순서대로 시도합니다.

        ① 서머노트 API — jQuery 가 있으면 가장 확실합니다
        ② 코드 보기(</>) 칸에 붙이고 다시 끄기 — 팀원이 손으로 하던 방식
        ③ 에디터 뒤의 원본 textarea 에 직접 쓰기
        """
        page = self.page

        if self._set_via_summernote_api(content) or self._set_via_codeview(content):
            return

        textarea = self._field("content")
        if textarea.count() == 0:
            textarea = page.locator("textarea").first
        if textarea.count() == 0:
            raise self._fail("본문을 넣을 자리를 찾지 못했습니다", "content")
        textarea.evaluate(
            "(el, html) => { el.value = html; el.dispatchEvent(new Event('change', {bubbles: true})); }",
            content,
        )
        editable = page.locator(".note-editable")
        if editable.count():
            editable.first.evaluate("(el, html) => { el.innerHTML = html; }", content)

    def _set_via_summernote_api(self, content: str) -> bool:
        try:
            return bool(
                self.page.evaluate(
                    """(html) => {
                        const $ = window.jQuery;
                        if (!$ || !$.fn || !$.fn.summernote) return false;
                        const $editor = $('.note-editor').first();
                        if (!$editor.length) return false;
                        // 서머노트는 원본 요소를 숨기고 그 바로 뒤에 에디터를 붙입니다.
                        const $note = $editor.prev();
                        if (!$note.length) return false;
                        $note.summernote('code', html);
                        return $note.summernote('code').length > 0;
                    }""",
                    content,
                )
            )
        except Exception as exc:
            log.debug("서머노트 API 경로 실패: %s", exc)
            return False

    def _set_via_codeview(self, content: str) -> bool:
        page = self.page
        toggle = page.locator(
            "button[data-event=codeview], .btn-codeview, .note-toolbar button:has-text('</>')"
        )
        codable = page.locator("textarea.note-codable")
        if toggle.count() == 0 or codable.count() == 0:
            return False

        try:
            toggle.first.click()
            codable.first.wait_for(state="visible", timeout=5_000)
            codable.first.fill(content)
            toggle.first.click()  # 코드 보기를 끄면 본문에 반영됩니다.
            page.wait_for_timeout(300)
            editable = page.locator(".note-editable").first
            return editable.count() > 0 and len(editable.inner_html()) > 0
        except Exception as exc:
            log.debug("코드 보기 경로 실패: %s", exc)
            return False

    # ----------------------------------------------------------- 등록

    def submit(self) -> None:
        page = self.page
        button = None

        for selector in ("form input[type=submit]", "form button[type=submit]"):
            found = page.locator(selector)
            if found.count():
                button = found.first
                break

        if button is None:
            for text in self.profile.submit_buttons:
                for found in (
                    page.get_by_role("button", name=text, exact=True),
                    page.locator(f"input[value='{text}']"),
                    page.get_by_role("link", name=text, exact=True),
                ):
                    if found.count():
                        button = found.first
                        break
                if button is not None:
                    break

        if button is None:
            raise self._fail("등록 버튼을 찾지 못했습니다", "submit")

        button.click()
        self._settle()

    # ----------------------------------------------------------- 한 편 올리기

    def publish(
        self,
        *,
        title: str,
        hit: int,
        images: Sequence[tuple[str, bytes]],
        compose: Callable[[list[str]], str],
    ) -> BoardPost:
        """글 한 편을 올립니다.

        `images` 를 먼저 올려 서버 주소를 받고, 그 주소들을 `compose` 에 넘겨 최종
        HTML 을 만든 뒤 본문에 넣습니다. 이미지 주소는 서버가 정하므로 이 순서가
        아니면 본문을 만들 수 없습니다.
        """
        self.open_write_form()
        self.fill_title(title)
        self.fill_hit(hit)
        self.ensure_html_mode()

        urls = [self.upload_image(data, name) for name, data in images]
        self.set_content(compose(urls))
        self.snapshot("before-submit")
        self.submit()

        post = self.find_post(title)
        if post is None:
            raise self._fail("등록을 눌렀지만 목록에서 그 글을 찾지 못했습니다", "after-submit")
        if not post.id:
            log.warning("글은 올라갔지만 글 번호를 읽지 못했습니다: %s", title[:40])
        return post

    # ----------------------------------------------------------- 정찰

    def inspect(self, out_dir: Path) -> Path:
        """로그인 → 목록 → 글쓰기 폼까지 가서 화면과 폼 구조를 떠 둡니다.

        새 사이트의 프로파일을 만들 때, 또는 사이트가 개편되어 자동화가 깨졌을 때
        사람이나 에이전트가 이 산출물을 보고 프로파일을 고칩니다.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts = out_dir
        report: dict[str, Any] = {"host": self.profile.host, "steps": []}

        self.login()
        report["steps"].append(
            {"step": "login", "url": self.page.url, "shot": self.snapshot("inspect-login")}
        )

        self.open_list()
        report["steps"].append(
            {"step": "list", "url": self.page.url, "shot": self.snapshot("inspect-list")}
        )
        report["list_links"] = self.page.locator("a[href]").evaluate_all(
            "els => els.slice(0, 80).map(e => "
            "({text: e.innerText.trim().slice(0, 60), href: e.getAttribute('href')}))"
        )

        try:
            self.open_write_form()
        except BoardError as exc:
            report["write_form_error"] = str(exc)
        else:
            report["steps"].append(
                {"step": "write", "url": self.page.url, "shot": self.snapshot("inspect-write")}
            )
            report["form_fields"] = self.page.locator("input, textarea, select, button").evaluate_all(
                """els => els.map(e => ({
                    tag: e.tagName.toLowerCase(), type: e.type || '', name: e.name || '',
                    id: e.id || '', value: (e.value || '').slice(0, 40),
                    row: (e.closest('tr') && e.closest('tr').children[0] || {}).innerText || ''
                }))"""
            )
            report["editor"] = {
                "summernote": self.page.locator(".note-editor").count() > 0,
                "toolbar_buttons": self.page.locator(".note-toolbar button").evaluate_all(
                    "els => els.map(e => e.getAttribute('data-event') "
                    "|| e.getAttribute('aria-label') || e.innerText)"
                ),
                "jquery": self.page.evaluate("() => !!(window.jQuery && window.jQuery.fn.summernote)"),
            }

        path = out_dir / "inspect.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _norm(text: str) -> str:
    return " ".join((text or "").split())
