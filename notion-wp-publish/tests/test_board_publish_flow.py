"""자체 게시판 발행 오케스트레이터 — 브라우저 없이 가짜 드라이버로 돌립니다.

확인하려는 것:
  · 발행 대상이 없으면 브라우저를 띄우지 않는가
  · 같은 제목이 이미 게시판에 있으면 다시 올리지 않고 노션만 되돌려 쓰는가
  · 이미지 → 본문 → 등록 순서가 지켜지고 조회수가 범위 안인가
  · 실패하면 '발행 오류'로 표시되는가, 로그인 실패는 원고 탓으로 돌리지 않는가
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import notionwp.publish as publish_mod
from fixtures import sample_page
from notionwp.board import BoardError, BoardPost, BoardProfile
from notionwp.board_publish import BoardPublisher
from notionwp.registry import build_config
from test_board_registry import board_row
from test_gate_schema import DEFAULTS, complete_page, text_prop
from test_publish_flow import FakeNotion

CONFIG = build_config(DEFAULTS, board_row(), platform="board")[0]
assert CONFIG is not None

PROFILE = BoardProfile(
    host="www.zeroclinic1.com",
    admin_url=CONFIG.board.admin_url,
    public_url="https://www.zeroclinic1.com/htm/boardseo_read.php?id={id}",
    hit_min=500,
    hit_max=1100,
)


class FakeBoard:
    """BoardClient 흉내. 호출 순서와 넘어온 값을 기록합니다."""

    opened = 0

    def __init__(self, *, existing: dict[str, str] | None = None, fail_login=False, fail_publish=False):
        self.calls: list[str] = []
        self.existing = existing or {}
        self.fail_login = fail_login
        self.fail_publish = fail_publish
        self.posts: list[dict] = []
        self._next = 300

    def factory(self, profile, user, password):
        FakeBoard.opened += 1
        self.credentials = (user, password)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("close")

    def login(self):
        self.calls.append("login")
        if self.fail_login:
            raise BoardError("로그인에 실패했습니다")

    def find_post(self, title):
        self.calls.append("find")
        if title in self.existing:
            pid = self.existing[title]
            return BoardPost(id=pid, title=title, link=PROFILE.public_link(pid))
        for post in self.posts:
            if post["title"] == title:
                return BoardPost(id=post["id"], title=title, link=PROFILE.public_link(post["id"]))
        return None

    def publish(self, *, title, hit, images, compose):
        self.calls.append("publish")
        if self.fail_publish:
            raise BoardError("등록 버튼을 찾지 못했습니다")
        urls = [f"/files/editor/{i}.jpg" for i, _ in enumerate(images, start=1)]
        html = compose(urls)
        self._next += 1
        self.posts.append({"id": str(self._next), "title": title, "hit": hit, "images": images, "html": html})
        return BoardPost(id=str(self._next), title=title, link=PROFILE.public_link(str(self._next)))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(publish_mod, "download", lambda url, session=None: b"\x89PNG fake")
    monkeypatch.setattr(publish_mod, "today_kst", lambda: __import__("datetime").date(2026, 8, 12))
    monkeypatch.setenv("BOARD_USER_ZEROCLINIC1", "admin")
    monkeypatch.setenv("BOARD_PASSWORD_ZEROCLINIC1", "secret")
    FakeBoard.opened = 0


def build(board: FakeBoard, pages=None, blocks=None, *, dry_run=False, cfg=CONFIG):
    notion = FakeNotion(pages or [complete_page()], blocks or sample_page())
    pub = BoardPublisher(
        cfg, dry_run=dry_run, notion=notion, client_factory=board.factory, profile=PROFILE
    )
    return pub, notion


# ------------------------------------------------------------------ 정상 경로


def test_happy_path_publishes_and_writes_back():
    board = FakeBoard()
    pub, notion = build(board)

    outcomes = pub.run()

    assert [o.published for o in outcomes] == [True]
    assert outcomes[0].link == "https://www.zeroclinic1.com/htm/boardseo_read.php?id=301"
    assert board.credentials == ("admin", "secret")
    # 로그인 → 중복 확인 → 등록 순서가 지켜져야 합니다.
    assert board.calls[:3] == ["login", "find", "publish"]

    page_id, props = notion.updates[-1]
    assert props["진행 상황"]["status"]["name"] == "게재완료"
    assert props["URL"]["url"] == "https://www.zeroclinic1.com/htm/boardseo_read.php?id=301"


def test_hit_count_is_random_within_the_profile_range():
    board = FakeBoard()
    pub, _ = build(board)
    pub.run()
    assert 500 <= board.posts[0]["hit"] <= 1100


def test_body_images_are_uploaded_and_placed_with_alts():
    board = FakeBoard()
    pub, _ = build(board)
    pub.run()

    post = board.posts[0]
    names = [name for name, _ in post["images"]]
    # 롱폼은 썸네일을 본문에 넣지 않으므로 본문 이미지 두 장만 올라갑니다.
    assert names == ["melasma-laser-sessions-1.jpg", "melasma-laser-sessions-2.jpg"]
    assert '<img src="/files/editor/1.jpg" alt="기미 레이저 치료 회차를 상담하는 진료 장면">' in post["html"]
    assert "<title>기미 레이저 횟수 | 클리어톤의원</title>" in post["html"]
    assert 'name="description"' in post["html"]
    assert "wp:paragraph" not in post["html"]


def test_shortform_puts_the_thumbnail_on_top():
    board = FakeBoard()
    page = complete_page(
        **{
            "유형": {"type": "select", "select": {"name": "숏폼"}},
            "본문 이미지": {"type": "files", "files": []},
        }
    )
    pub, _ = build(board, pages=[page])
    pub.run()

    post = board.posts[0]
    assert [n for n, _ in post["images"]] == ["melasma-laser-sessions-thumbnail.png"]
    body = post["html"].split("</h1>", 1)[1]
    assert body.lstrip().startswith('<p><br></p><div><img src="/files/editor/1.jpg"')


def test_slug_is_optional_for_the_board():
    board = FakeBoard()
    page = complete_page(**{"슬러그": text_prop("")})
    pub, _ = build(board, pages=[page])
    outcomes = pub.run()
    assert outcomes[0].published
    # 슬러그가 없으면 페이지 ID 로 파일 이름을 만듭니다.
    assert board.posts[0]["images"][0][0].startswith("post-e2868fa2-1.")


# ------------------------------------------------------------------ 중복·대상 없음


def test_no_candidates_means_no_browser():
    board = FakeBoard()
    page = complete_page(**{"진행 상황": {"type": "status", "status": {"name": "작성중"}}})
    pub, notion = build(board, pages=[page])
    outcomes = pub.run()

    assert FakeBoard.opened == 0
    assert board.calls == []
    assert outcomes[0].skipped
    # 대상이 없어도 실행 로그는 남습니다 — 단계 이름이 게시판 발행이어야 합니다.
    assert notion.created[-1][1]["단계"]["select"]["name"] == "게시판 발행"


def test_existing_post_is_not_republished_but_notion_is_repaired():
    """지난 회차에 등록까지 되고 노션 쓰기만 실패한 경우를 되살립니다."""
    board = FakeBoard(existing={"기미 레이저 몇 회": "161"})
    pub, notion = build(board)
    outcomes = pub.run()

    assert "publish" not in board.calls
    assert outcomes[0].skipped and "이미 게시판" in outcomes[0].reasons[0]
    assert outcomes[0].link.endswith("id=161")
    _, props = notion.updates[-1]
    assert props["진행 상황"]["status"]["name"] == "게재완료"
    assert props["URL"]["url"].endswith("id=161")


def test_dry_run_touches_nothing():
    board = FakeBoard()
    pub, notion = build(board, dry_run=True)
    outcomes = pub.run()

    assert FakeBoard.opened == 0
    assert outcomes[0].skipped and "dry-run" in outcomes[0].reasons[0]
    assert notion.updates == [] and notion.created == []


# ------------------------------------------------------------------ 실패


def test_publish_failure_marks_the_row_as_error():
    board = FakeBoard(fail_publish=True)
    pub, notion = build(board)
    outcomes = pub.run()

    assert outcomes[0].error and "등록 버튼" in outcomes[0].error
    _, props = notion.updates[-1]
    assert props["진행 상황"]["status"]["name"] == "발행 오류"


def test_login_failure_does_not_blame_the_article():
    board = FakeBoard(fail_login=True)
    pub, notion = build(board)
    outcomes = pub.run()

    assert outcomes[0].error and "로그인" in outcomes[0].error
    assert notion.updates == [], "로그인 실패는 원고 탓이 아니므로 플래너 상태를 바꾸지 않습니다"


def test_missing_credentials_fail_before_the_browser(monkeypatch):
    monkeypatch.delenv("BOARD_USER_ZEROCLINIC1")
    board = FakeBoard()
    pub, _ = build(board)
    outcomes = pub.run()
    assert FakeBoard.opened == 0
    assert "BOARD_USER_ZEROCLINIC1" in outcomes[0].error


# ------------------------------------------------------------------ 준비 단계


def test_prepare_writes_a_plan_without_a_slug(tmp_path):
    board = FakeBoard()
    page = complete_page(**{"슬러그": text_prop("")})
    pub, _ = build(board, pages=[page])
    outcomes = pub.prepare(tmp_path)

    assert outcomes[0].prepared
    plan = Path(outcomes[0].plan_path)
    assert plan.exists()
    assert (plan.parent / "images" / "1.jpg").exists()


def test_plan_alts_are_used_when_present(tmp_path):
    board = FakeBoard()
    pub, _ = build(board)
    pub.prepare(tmp_path)

    import json

    plan_path = next(tmp_path.rglob("plan.json"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for img in plan["images"]:
        img["alt"] = f"검수한 ALT {img['n']}"
    plan["thumbnail_alt"] = "검수한 썸네일 ALT"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    pub2, _ = build(board)
    pub2.plan_root = tmp_path
    pub2.run()
    assert 'alt="검수한 ALT 1"' in board.posts[0]["html"]


def test_unfilled_plan_alts_block_publishing(tmp_path):
    board = FakeBoard()
    pub, notion = build(board)
    pub.prepare(tmp_path)

    pub2, notion2 = build(board)
    pub2.plan_root = tmp_path
    outcomes = pub2.run()
    assert outcomes[0].error and "ALT" in outcomes[0].error
    assert "publish" not in board.calls
