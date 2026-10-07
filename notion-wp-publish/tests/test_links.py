# -*- coding: utf-8 -*-
"""글 끝 '참고 자료'·'관련 글' 줄 링크 걸기.

원고는 이 줄을 글자로만 씁니다. 사람이 발행 뒤 손으로 걸던 것을 발행 단계가
대신합니다 — 빠지거나, 엇나가거나, 같은 학회를 다른 주소로 거는 일이 없도록.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import block, h2, para, rt
from notionwp.links import LinkError, LinkRules, apply, load, make_related_resolver, path_for
from notionwp.richtext import to_html

RULES = LinkRules(
    client="어떤병원",
    references={"대한신경외과학회": "https://www.neurosurgery.or.kr/", "서울아산병원": "https://www.amc.seoul.kr/"},
    related=True,
)


def links_of(blocks):
    return [(n["plain_text"], n.get("href")) for b in blocks for n in b["paragraph"]["rich_text"] if n.get("href")]


# ------------------------------------------------------------------ 참고 자료


def test_reference_names_get_their_official_urls():
    blocks, warnings = apply([para("참고 자료: 대한신경외과학회, 서울아산병원")], RULES)

    assert links_of(blocks) == [
        ("대한신경외과학회", "https://www.neurosurgery.or.kr/"),
        ("서울아산병원", "https://www.amc.seoul.kr/"),
    ]
    assert warnings == []
    # 렌더되면 줄머리는 굵게, 이름은 링크입니다.
    html = to_html(blocks[0]["paragraph"]["rich_text"])
    assert html.startswith("<strong>참고 자료: </strong>")
    assert '<a href="https://www.neurosurgery.or.kr/">대한신경외과학회</a>' in html


@pytest.mark.parametrize("line", [
    "참고자료: 대한신경외과학회",
    "출처 및 참고자료: 대한신경외과학회",
    "**참고 자료**: 대한신경외과학회",
    "참고 자료 : 대한신경외과학회 · 서울아산병원",
])
def test_every_spelling_of_the_reference_line_is_recognised(line):
    """원고가 줄머리를 조금씩 다르게 씁니다. 전부 받아야 합니다."""
    blocks, _ = apply([para(line)], RULES)
    assert links_of(blocks), line


def test_an_unknown_institution_is_left_as_text_not_invented():
    """표에 없는 이름에 주소를 지어내면 안 됩니다. 글자로 두고 경고합니다."""
    blocks, warnings = apply([para("참고 자료: 대한신경외과학회, 어디학회")], RULES)

    assert links_of(blocks) == [("대한신경외과학회", "https://www.neurosurgery.or.kr/")]
    assert "어디학회" in to_html(blocks[0]["paragraph"]["rich_text"])
    assert any("어디학회" in w for w in warnings)


def test_a_line_that_already_has_links_is_left_alone():
    """사람이나 원고가 이미 건 링크는 그 뜻을 존중합니다."""
    already = block("paragraph", rt("참고 자료: "), rt("대한신경외과학회", href="https://example.org/x"))
    blocks, warnings = apply([already], RULES)

    assert links_of(blocks) == [("대한신경외과학회", "https://example.org/x")]
    assert warnings == []


def test_ordinary_paragraphs_and_headings_are_untouched():
    body = [h2("어떻게 진단하나요?"), para("설명: 이것은 참고 자료가 아닙니다."), para("참고로 말씀드리면")]
    blocks, warnings = apply(body, RULES)
    assert blocks == body
    assert warnings == []


def test_no_rules_means_no_change():
    body = [para("참고 자료: 대한신경외과학회")]
    assert apply(body, None) == (body, [])


# ------------------------------------------------------------------ 관련 글


def resolver():
    rows = [
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "신경차단술이란? 적응증·효과"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/nerve-block/"}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "허리디스크 주사치료, 계속 맞아도 되나요?"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/spinal-injections-limit/"}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "허리디스크(요추 추간판 탈출증), 원인·증상·치료"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/herniated-disc/"}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "척추관협착증이란? 증상·원인"}]},
                        "진행 상황": {"type": "status", "status": {"name": "컨펌 진행 중"}},
                        "URL": {"type": "url", "url": ""}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "하지 방사통, 네이버에 올린 글"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.naver.com/x/1"}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "척추관협착증이란? 증상·원인과 치료 판단 기준"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/spinal-stenosis/"}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "척추관 협착증 수술은 언제 고려하나요?"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/spinal-stenosis-surgery-timing/"}}},
    ]
    return make_related_resolver(rows, title_prop="제목", url_prop="URL", status_prop="진행 상황", done="게재완료", site="https://blog.test")


def test_related_links_never_leave_the_clients_site():
    """플래너에는 네이버에 올린 글도 게재완료로 섞여 있습니다. 거기로 보내면 안 됩니다."""
    assert resolver()("하지 방사통") is None


def test_the_glossary_article_wins_over_a_longer_title_on_the_same_term():
    """'척추관협착증' 은 '…이란?' 용어 글로 가야지 '…수술은 언제' 글로 가면 안 됩니다."""
    assert resolver()("척추관협착증") == "https://blog.test/spinal-stenosis/"


def test_a_term_that_heads_exactly_one_title_resolves_even_among_lookalikes():
    """'허리디스크' 는 주사치료 글과 용어 글이 같이 있어도, 괄호 앞 첫 마디가 같은 쪽 하나로 갑니다."""
    assert resolver()("허리디스크") == "https://blog.test/herniated-disc/"


def test_related_items_link_to_published_rows_by_title():
    blocks, warnings = apply([para("관련 글: 신경차단술 · 신경차단술이란?")], RULES, resolve_related=resolver())
    assert links_of(blocks) == [
        ("신경차단술", "https://blog.test/nerve-block/"),
        ("신경차단술이란?", "https://blog.test/nerve-block/"),
    ]
    assert warnings == []


def test_a_title_ending_in_ran_question_matches_its_term():
    """'경막외 스테로이드 주사' 는 '경막외 스테로이드 주사란? 신경차단술과의 차이' 로 가야 합니다."""
    rows = [
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "경막외 스테로이드 주사란? 신경차단술과의 차이"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/epidural-steroid-injection/"}}},
    ]
    r = make_related_resolver(rows, title_prop="제목", url_prop="URL", status_prop="진행 상황", done="게재완료")
    assert r("경막외 스테로이드 주사") == "https://blog.test/epidural-steroid-injection/"


def test_a_bare_prefix_match_is_not_enough():
    """'디스크' 가 '디스크내장증, …' 으로 가면 안 됩니다. 시작만 같은 것은 맞춤이 아닙니다."""
    rows = [
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "디스크내장증, 원인·증상·치료"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/internal-disc-disruption/"}}},
    ]
    r = make_related_resolver(rows, title_prop="제목", url_prop="URL", status_prop="진행 상황", done="게재완료")
    assert r("디스크") is None


def test_a_truly_ambiguous_item_is_not_guessed():
    """첫 마디까지 같은 글이 둘이면 고르지 않습니다. 엇나간 링크가 바로 이렇게 생겼습니다."""
    rows = [
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "디스크, 원인"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/a/"}}},
        {"properties": {"제목": {"type": "title", "title": [{"plain_text": "디스크(추간판), 구조"}]},
                        "진행 상황": {"type": "status", "status": {"name": "게재완료"}},
                        "URL": {"type": "url", "url": "https://blog.test/b/"}}},
    ]
    r = make_related_resolver(rows, title_prop="제목", url_prop="URL", status_prop="진행 상황", done="게재완료")
    blocks, warnings = apply([para("관련 글: 디스크")], RULES, resolve_related=r)
    assert blocks == [] and any("디스크" in w for w in warnings)


def test_unpublished_or_unknown_articles_are_dropped_not_linked():
    """게재 전인 글, 없는 글로 가는 링크는 만들지 않습니다. 항목을 뺍니다."""
    blocks, warnings = apply([para("관련 글: 미발행 글 · 없는 글 · 신경차단술")], RULES, resolve_related=resolver())
    html = to_html(blocks[0]["paragraph"]["rich_text"])
    assert "미발행 글" not in html and "없는 글" not in html
    assert links_of(blocks) == [("신경차단술", "https://blog.test/nerve-block/")]
    assert not html.rstrip().endswith(",")


def test_a_related_line_with_nothing_real_is_removed_entirely():
    blocks, warnings = apply([h2("마무리"), para("관련 글: 없는 글 · 또 없는 글")], RULES, resolve_related=resolver())
    assert [b["type"] for b in blocks] == ["heading_2"]
    assert any("줄을 뺐습니다" in w for w in warnings)


def test_related_lines_are_untouched_when_the_client_has_not_opted_in():
    rules = LinkRules(client="x", references={}, related=False)
    body = [para("관련 글: 신경차단술")]
    assert apply(body, rules, resolve_related=resolver()) == (body, [])


# ------------------------------------------------------------------ 파일


def test_the_real_champodonamu_file_loads_and_covers_the_guideline_institutions():
    rules = load("참포도나무병원")
    assert rules is not None and rules.related
    for name in ("대한신경외과학회", "대한척추신경외과학회", "대한통증학회", "대한마취통증의학회",
                 "대한류마티스학회", "대한재활의학회", "보건복지부 국가건강정보포털", "서울대학교병원", "서울아산병원"):
        assert rules.reference_url(name), name


def test_a_bad_url_in_the_file_is_reported(tmp_path):
    path_for("어떤병원", tmp_path).write_text(json.dumps({"references": {"학회": "www.no-scheme.kr"}}), encoding="utf-8")
    with pytest.raises(LinkError, match="http"):
        load("어떤병원", tmp_path)


def test_no_file_means_none(tmp_path):
    assert load("어떤병원", tmp_path) is None
