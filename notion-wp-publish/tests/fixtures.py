"""실제 원고 페이지(클리어톤의원 '기미 레이저 몇 회 받아야 할까')의 골격을 그대로 옮긴 픽스처.

노션 API가 돌려주는 블록 모양을 최소한으로 재현합니다.
"""

from __future__ import annotations

from typing import Any

Block = dict[str, Any]


def rt(text: str, *, bold: bool = False, code: bool = False, href: str | None = None) -> dict:
    return {
        "type": "text",
        "plain_text": text,
        "href": href,
        "annotations": {
            "bold": bold,
            "italic": False,
            "strikethrough": False,
            "underline": False,
            "code": code,
            "color": "default",
        },
    }


def block(btype: str, *nodes: dict, children: list[Block] | None = None, **payload) -> Block:
    body = {"rich_text": list(nodes)}
    body.update(payload)
    out: Block = {"object": "block", "type": btype, btype: body}
    if children is not None:
        out["_children"] = children
        out["has_children"] = True
    return out


def para(text: str = "", **kw) -> Block:
    return block("paragraph", *( [rt(text, **kw)] if text else [] ))


def h1(text: str) -> Block:
    return block("heading_1", rt(text))


def h2(text: str) -> Block:
    return block("heading_2", rt(text))


def h3(text: str) -> Block:
    return block("heading_3", rt(text))


def bullet(*nodes: dict, children: list[Block] | None = None) -> Block:
    return block("bulleted_list_item", *nodes, children=children)


def divider() -> Block:
    return {"object": "block", "type": "divider", "divider": {}}


def sample_page() -> list[Block]:
    """상단 안내 → 가이드 토글 → 자동생성 callout → 메타 → H1 → 본문 → 검수용 섹션."""
    return [
        block(
            "callout",
            rt("모든 콘텐츠는 하단 토글(▶)을 열어 콘텐츠 가이드를 확인한 후 작성해주시기 바랍니다."),
        ),
        block(
            "toggle",
            rt("콘텐츠 가이드"),
            children=[para("이 안은 기획안입니다. 발행 본문에 쓰면 안 됩니다.")],
        ),
        divider(),
        para(),
        para(),
        divider(),
        block(
            "callout",
            rt("자동 생성 원고 · 원고 자동화 에이전트", bold=True),
            rt(" 생성 2026-08-10 21:33 (Asia/Seoul) · 메인 키워드: 기미 레이저 횟수"),
        ),
        para("메타 디스크립션", bold=True),
        para("기미 레이저 횟수는 색소의 깊이와 종류, 피부 상태에 따라 달라집니다."),
        h1("기미 레이저 몇 회 받아야 할까 | 색소 깊이별 치료 횟수와 효과 시점 정리"),
        para("기미 레이저 횟수는 정해진 숫자가 아니라, 색소가 자리한 깊이와 병변의 종류에 따라 달라집니다."),
        h2("기미 레이저 횟수, 먼저 알아둘 핵심 포인트 7가지"),
        block("numbered_list_item", rt("기미는 한 번에 끝나는 색소가 아닙니다.")),
        h2("기미 레이저 횟수는 왜 사람마다 다를까?"),
        para("기미 레이저 횟수가 갈리는 가장 큰 이유는 색소가 놓인 깊이 때문입니다.", bold=True),
        h3("병변 종류에 따라 반응이 갈리는 이유"),
        {
            "object": "block",
            "type": "table",
            "table": {"table_width": 3, "has_column_header": True},
            "_children": [
                {
                    "object": "block",
                    "type": "table_row",
                    "table_row": {
                        "cells": [[rt("색소 병변")], [rt("깊이")], [rt("회차 경향")]]
                    },
                },
                {
                    "object": "block",
                    "type": "table_row",
                    "table_row": {
                        "cells": [[rt("기미")], [rt("표피와 진피 혼재")], [rt("긴 호흡으로 관리")]]
                    },
                },
            ],
        },
        h2("기미 치료 기간을 계획할 때 참고할 기준"),
        block(
            "paragraph",
            rt("국제 학술 문헌은 "),
            rt("체계적 문헌고찰", href="https://pmc.ncbi.nlm.nih.gov/articles/PMC12696807/"),
            rt("에 따르면 2회에서 12회 범위로 진행되었습니다."),
        ),
        h2("강남 기미 레이저 진료에서 확인하면 좋은 것"),
        block("to_do", rt("내 병변이 기미인지 흑자인지 감별 과정을 거치는지"), checked=False),
        block("to_do", rt("색소의 깊이를 나눠서 접근하는 계획인지"), checked=False),
        h2("[FAQ] 기미 레이저 치료 자주 묻는 질문"),
        h3("Q1. 기미 레이저는 몇 번 받아야 효과를 기대할 수 있나요?"),
        para("병변의 깊이와 피부 상태에 따라 다릅니다.", bold=True),
        para("감별 진단을 거쳐 치료 간격과 횟수를 계획하는 것이 일반적입니다."),
        h3("Q2. 회차를 많이 받을수록 좋아지나요?"),
        para("회차의 수보다 누적되는 에너지와 간격의 설계가 더 중요합니다.", bold=True),
        h2("기미 레이저 횟수보다 먼저 정해야 할 것"),
        para("기미 레이저 횟수는 치료의 출발점이 아니라 결과에 가깝습니다."),
        block(
            "paragraph",
            rt("👉 클리어톤의원 진료 안내 확인하기 ("),
            rt("https://cleartone.co.kr/", href="https://cleartone.co.kr/"),
            rt(")"),
        ),
        divider(),
        h2("📋 작성 메타 정보"),
        bullet(rt("제목 출처", bold=True), rt(": 팀 지정 제목을 그대로 사용")),
        bullet(rt("H태그 개수", bold=True), rt(": H1 1개 / H2 9개 / H3 12개")),
        h2("🔧 구조화 제안"),
        bullet(
            rt("스키마 마크업", bold=True),
            rt(": FAQPage (FAQ 6문항), Article, MedicalClinic (병원 정보 블록에 적용)"),
        ),
        bullet(
            rt("이미지 alt 텍스트 가이드", bold=True),
            children=[
                bullet(rt("도입부: "), rt("기미 레이저 치료 회차를 상담하는 진료 장면", code=True)),
                bullet(rt("병변 비교표 상단: "), rt("기미 흑자 검버섯 색소 깊이 비교", code=True)),
                bullet(rt("회차 설명 섹션: "), rt("색소 레이저 회차별 경과 확인 과정", code=True)),
                bullet(
                    rt("클로징: "),
                    rt("클리어톤의원 색소 레이저 장비", code=True),
                    rt(" (치료 전후 이미지는 사전심의 이슈로 사용 지양)"),
                ),
            ],
        ),
        bullet(rt("내부 링크 제안", bold=True), rt(": 검버섯과 기미 차이 콘텐츠로 상호 연결 권장")),
        h2("✅ 셀프 점검 결과"),
        bullet(rt("E-E-A-T", bold=True), rt(": 경험 · 전문성 · 권위 · 신뢰 반영")),
        h2("⚠️ 사용자 확인 요청"),
        block("numbered_list_item", rt("발행 전 브라우저 최종 접속 확인 권장")),
    ]


def page_with_evidence_table() -> list[Block]:
    """'근거 자료 표 (검수용)'이 굵은 문단으로 들어간 변형."""
    return [
        h1("올타이트 리프팅이란?"),
        h2("올타이트 리프팅의 원리"),
        para("진피층을 표적하는 고주파 유전가열 방식입니다."),
        para("근거 자료 표 (검수용)", bold=True),
        {
            "object": "block",
            "type": "table",
            "table": {"table_width": 2, "has_column_header": True},
            "_children": [],
        },
    ]
