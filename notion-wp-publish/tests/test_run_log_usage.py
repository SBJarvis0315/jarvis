# -*- coding: utf-8 -*-
"""실행 로그 — 소요 시간 기록과 단계별 요약."""

from __future__ import annotations

from dataclasses import replace

from notionwp.config import RunLogConfig
from notionwp.runlog import RunLogger, Summary
from notionwp.thumbnails import Outcome, Report


class FakeNotion:
    def __init__(self):
        self.pages: list[tuple[str, dict]] = []

    def create_page(self, database_id, properties):
        self.pages.append((database_id, properties))
        return {"id": "page-1"}


CFG = RunLogConfig(database_id="db-1")


def write(outcomes, **kwargs):
    notion = FakeNotion()
    RunLogger(CFG, "어떤의원", notion).write(outcomes, **kwargs)
    return notion.pages[0][1] if notion.pages else None


def test_duration_is_recorded_in_minutes():
    props = write([], duration_min=2.5)
    assert props["소요 시간(분)"] == {"number": 2.5}


def test_duration_is_rounded():
    props = write([], duration_min=1.23456)
    assert props["소요 시간(분)"] == {"number": 1.23}


def test_duration_is_omitted_when_not_measured():
    assert "소요 시간(분)" not in write([])


def test_token_columns_are_left_for_the_agent_to_fill():
    """스크립트는 자기 토큰 사용량을 알 수 없으므로 비워 둡니다."""
    props = write([], duration_min=1.0)
    assert "사용 토큰" not in props
    assert "비용(USD)" not in props


def test_a_supplied_summary_is_used_as_is():
    props = write([], summary=Summary(result="성공", count=7, detail="직접 만든 요약"))
    assert props["처리 건수"] == {"number": 7}
    assert props["결과"] == {"select": {"name": "성공"}}
    assert "직접 만든 요약" in props["상세"]["rich_text"][0]["text"]["content"]


def test_logging_is_skipped_without_a_database():
    notion = FakeNotion()
    RunLogger(replace(CFG, database_id=""), "어떤의원", notion).write([])
    assert notion.pages == []


# ------------------------------------------------- 썸네일 단계 요약

def test_thumbnail_summary_counts_only_what_was_made():
    report = Report(client="어떤의원", outcomes=[
        Outcome(title="가", made=True),
        Outcome(title="나", skipped="썸네일이 이미 있음"),
        Outcome(title="다", error="렌더 실패"),
    ])
    summary = report.summarize()
    assert summary.result == "부분 성공"
    assert summary.count == 1
    assert "썸네일 1건 · 실패 1건" in summary.detail


def test_thumbnail_summary_when_nothing_matched():
    assert Report(client="어떤의원").summarize().result == "대상 없음"


def test_thumbnail_summary_all_good():
    report = Report(client="어떤의원", outcomes=[Outcome(title="가", made=True)])
    assert report.summarize().result == "성공"


def test_thumbnail_stage_name_is_written():
    notion = FakeNotion()
    RunLogger(replace(CFG, stage="썸네일 생성"), "어떤의원", notion).write([])
    assert notion.pages[0][1]["단계"] == {"select": {"name": "썸네일 생성"}}
