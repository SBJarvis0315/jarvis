"""실행 결과를 노션 '자동화 실행 로그' DB에 남기는 동작.

확인하려는 것:
  · 실제로 발행한 회차에만 로그가 남는가 (--dry-run·--draft 는 남기지 않음)
  · 결과 판정(성공/부분 성공/실패/대상 없음)이 맞는가
  · 로그 쓰기가 실패해도 발행 결과가 흔들리지 않는가
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import sample_page
from notionwp.config import RunLogConfig
from notionwp.publish import Outcome, Publisher
from notionwp.runlog import RunLogger, summarize_for_log
from test_gate_schema import CONFIG, complete_page
from test_publish_flow import FakeNotion, FakeWordPress, _no_network  # noqa: F401

LOG_DB = "3b368fa2-06ff-81e7-9451-c0241aa263fb"
OFF = replace(CONFIG, run_log=RunLogConfig())


def run(cfg=CONFIG, *, pages=None, wp=None, **kwargs):
    notion = FakeNotion(pages or [complete_page()], sample_page())
    publisher = Publisher(cfg, notion=notion, wp=wp or FakeWordPress(), **kwargs)
    return notion, publisher.run()


def logged(notion) -> dict:
    assert len(notion.created) == 1, notion.created
    database_id, props = notion.created[0]
    assert database_id == LOG_DB
    return props


def value(props: dict, name: str) -> str:
    prop = props[name]
    if "title" in prop:
        return prop["title"][0]["text"]["content"]
    if "rich_text" in prop:
        return prop["rich_text"][0]["text"]["content"]
    if "select" in prop:
        return prop["select"]["name"]
    return prop


# ------------------------------------------------------------------ 결과 판정


def out(title: str = "제목", **kwargs) -> Outcome:
    return Outcome(page_id="p", title=title, **kwargs)


def test_result_by_outcome_mix():
    assert summarize_for_log([out(published=True)]).result == "성공"
    assert summarize_for_log([out(error="터짐")]).result == "실패"
    assert summarize_for_log([out(published=True), out(error="터짐")]).result == "부분 성공"
    assert summarize_for_log([out(skipped=True, reasons=["유형이 대상 아님"])]).result == "대상 없음"
    assert summarize_for_log([]).result == "대상 없음"


def test_count_is_published_only():
    summary = summarize_for_log([out(published=True), out(error="x"), out(skipped=True)])
    assert summary.count == 1


def test_detail_hides_rows_still_being_written():
    summary = summarize_for_log(
        [
            out(published=True, link="https://blog.test/a"),
            out(title="아직 작성 중", skipped=True, reasons=["진행 상황이 '시작 전'"]),
            out(title="이미지 빠짐", skipped=True, reasons=["썸네일이 비어 있음"]),
        ]
    )
    assert "https://blog.test/a" in summary.detail
    assert "아직 작성 중" not in summary.detail  # 매일 쌓이는 행이라 로그를 덮습니다
    assert "이미지 빠짐" in summary.detail  # 발행 직전까지 갔다 걸린 것은 보여줍니다


# ------------------------------------------------------------------ 기록 시점


def test_publish_run_writes_one_row():
    notion, outcomes = run()
    props = logged(notion)

    assert value(props, "결과") == "성공"
    assert value(props, "고객사") == "클리어톤의원"
    assert props["처리 건수"]["number"] == 1
    assert value(props, "단계") == "워드프레스 발행"
    assert "워드프레스 발행" in value(props, "실행")
    assert props["실행일시"]["date"]["start"].endswith("+09:00")


def test_dry_run_and_draft_leave_no_trace():
    notion, _ = run(dry_run=True)
    assert notion.created == []

    notion, _ = run(draft=True)
    assert notion.created == []


def test_no_targets_still_logs():
    page = complete_page()
    page["properties"]["진행 상황"] = {"type": "status", "status": {"name": "시작 전"}}

    notion, _ = run(pages=[page])
    props = logged(notion)

    assert value(props, "결과") == "대상 없음"
    assert props["처리 건수"]["number"] == 0


def test_disabled_when_no_database_configured():
    notion, outcomes = run(OFF)
    assert notion.created == []
    assert outcomes[0].published  # 발행은 그대로 됩니다


# ------------------------------------------------------------------ 실패 격리


def test_log_failure_does_not_break_publishing():
    class Exploding(FakeNotion):
        def create_page(self, database_id, properties):
            raise RuntimeError("로그 DB 권한 없음")

    notion = Exploding([complete_page()], sample_page())
    outcomes = Publisher(CONFIG, notion=notion, wp=FakeWordPress()).run()

    assert outcomes[0].published
    assert outcomes[0].error == ""


def test_logger_is_silent_without_database_id():
    logger = RunLogger(RunLogConfig(), "고객사", notion=None)
    assert not logger.enabled
    logger.write([out(published=True)])  # notion 이 None 이어도 터지지 않습니다
