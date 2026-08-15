#!/usr/bin/env python3
"""네이버 브랜드블로그 원고가 고객사 지침을 지켰는지 검증한다.

초안 파일은 파트 경계를 <<파트명>> ... <</파트명>> 마커로 표시한다.
--emit 을 주면 마커를 지운 최종 원고를 그 경로에 쓴다.
"""
import argparse
import re
import sys
import unicodedata

# 파트명 -> (표시명, 최소 글자수, 초안 마커 목록)
PARTS = [
    ("결론 선제시", 200, ["결론선제시", "결론선제시2"]),
    ("서론", 300, ["서론"]),
    ("소제목1", 400, ["소제목1", "소제목1b"]),
    ("소제목2", 400, ["소제목2", "소제목2b"]),
    ("소제목3", 400, ["소제목3", "소제목3b"]),
    ("소제목4", 150, ["소제목4", "소제목4b"]),
    ("마무리", 350, ["마무리"]),
]

BANNED = ["흔들", "갈린", "새겨", "좌우", "판가름", "드러난", "결정된", "이어진"]
ALLOWED_SYMBOLS = "✔✓"
MIN_TABLES = 9
MIN_TOTAL_WITH_TABLES = 3000


def count(text):
    text = text.replace("**", "")
    return len(text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))


def section(raw, name):
    m = re.search(r"<<%s>>(.*?)<</%s>>" % (name, name), raw, re.S)
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--emit", help="마커를 제거한 최종 원고를 쓸 경로")
    args = ap.parse_args()

    raw = open(args.draft, encoding="utf-8").read()
    failures = []

    body_total = 0
    for label, minimum, markers in PARTS:
        n = sum(count(section(raw, m)) for m in markers)
        body_total += n
        ok = n >= minimum
        if not ok:
            failures.append("%s %d자 (최소 %d자)" % (label, n, minimum))
        print("%-12s %5d / %-4d %s" % (label, n, minimum, "OK" if ok else "FAIL"))

    print("본문 합계(표 제외): %d" % body_total)

    opened, closed = raw.count("[표]"), raw.count("[/표]")
    print("표 블록: %d (닫힘 %d)" % (opened, closed))
    if opened != closed:
        failures.append("표 태그 짝이 맞지 않습니다 (%d / %d)" % (opened, closed))
    if opened < MIN_TABLES:
        failures.append("표 블록 %d개 (최소 %d개)" % (opened, MIN_TABLES))

    quotes = raw.count("[인용구]")
    print("인용구: %d, 이미지: %d" % (quotes, raw.count("[이미지]")))
    if quotes < 6:
        failures.append("인용구 %d개 (소제목 4 + 요약 및 정리 + 클로징 = 6개 이상)" % quotes)

    clean = re.sub(r"<</?[^>]+>>", "", raw).replace("**", "")
    total = count(clean)
    print("전체 글자수(표 포함): %d" % total)
    if total < MIN_TOTAL_WITH_TABLES:
        failures.append("전체 %d자 (권장 %d자 이상)" % (total, MIN_TOTAL_WITH_TABLES))

    for word in BANNED:
        for m in re.finditer(word, raw):
            ctx = raw[max(0, m.start() - 25):m.start() + 20].replace("\n", " ")
            failures.append("금지 서술어 '%s' — ...%s..." % (word, ctx))

    emoji = {c for c in raw
             if unicodedata.category(c) == "So" and c not in ALLOWED_SYMBOLS}
    if emoji:
        failures.append("본문 이모지 사용: %s" % " ".join(sorted(emoji)))

    if args.emit:
        out = re.sub(r"<</?[^>]+>>\n?", "", raw)
        out = re.sub(r"\n{4,}", "\n\n\n", out).strip() + "\n"
        open(args.emit, "w", encoding="utf-8").write(out)
        print("최종 원고 저장: %s" % args.emit)

    if failures:
        print("\n미충족 %d건" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("\n지침 전 항목 충족")
    return 0


if __name__ == "__main__":
    sys.exit(main())
