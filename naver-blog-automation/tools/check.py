#!/usr/bin/env python3
"""원고가 고객사 지침을 지켰는지 검증한다.

초안은 파트 경계를 <<파트명>> ... <</파트명>> 마커로 표시한다.
--emit 을 주면 마커를 지운 최종 원고를 그 경로에 쓴다.

  python3 tools/check.py draft.txt --mode info
  python3 tools/check.py draft.txt --mode paper --keyword "라식수술후관리" --emit final.txt
"""
import argparse
import re
import sys
import unicodedata
from collections import Counter

# mode -> [(표시명, 최소 글자수, 초안 마커 목록)]
SPEC = {
    "info": [
        ("결론 선제시", 200, ["결론선제시", "결론선제시2"]),
        ("서론", 300, ["서론"]),
        ("소제목1", 400, ["소제목1", "소제목1b"]),
        ("소제목2", 400, ["소제목2", "소제목2b"]),
        ("소제목3", 400, ["소제목3", "소제목3b"]),
        ("소제목4", 150, ["소제목4", "소제목4b"]),
        ("마무리", 350, ["마무리"]),
    ],
    "paper": [
        ("서론", 300, ["서론"]),
        ("소제목1", 450, ["소제목1"]),
        ("소제목2", 450, ["소제목2"]),
        ("소제목3", 450, ["소제목3"]),
        ("마무리", 150, ["마무리"]),
    ],
}

BANNED_VERBS = ["흔들", "갈린", "새겨", "좌우", "판가름", "드러난", "결정된", "이어진"]
BANNED_CLAIMS = ["최고", "완치", "100%", "부작용 없음", "국내 유일", "1위", "무통"]
ALLOWED_SYMBOLS = "✔✓"


def count(text):
    text = text.replace("**", "")
    return len(text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))


def section(raw, name):
    m = re.search(r"<<%s>>(.*?)<</%s>>" % (name, name), raw, re.S)
    return m.group(1) if m else ""


def body_without_title(raw):
    """첫 줄(제목 후보)을 제외한 본문. 키워드 카운팅에 쓴다."""
    lines = raw.splitlines()
    return "\n".join(lines[1:]) if lines else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--mode", choices=("info", "paper"), default="info")
    ap.add_argument("--keyword", help="논문글 모드에서 본문 5회 삽입을 검사할 메인 키워드")
    ap.add_argument("--emit", help="마커를 제거한 최종 원고를 쓸 경로")
    args = ap.parse_args()

    raw = open(args.draft, encoding="utf-8").read()
    fails = []

    total = 0
    for label, minimum, markers in SPEC[args.mode]:
        n = sum(count(section(raw, m)) for m in markers)
        total += n
        ok = n >= minimum
        if not ok:
            fails.append("%s %d자 (최소 %d자)" % (label, n, minimum))
        print("%-12s %5d / %-4d %s" % (label, n, minimum, "OK" if ok else "FAIL"))
    print("본문 합계: %d" % total)

    clean = re.sub(r"<</?[^>]+>>", "", raw).replace("**", "")
    whole = count(clean)

    if args.mode == "info":
        opened, closed = raw.count("[표]"), raw.count("[/표]")
        print("표 블록: %d (닫힘 %d)" % (opened, closed))
        if opened != closed:
            fails.append("표 태그 짝 불일치 (%d / %d)" % (opened, closed))
        if opened < 9:
            fails.append("표 블록 %d개 (최소 9개)" % opened)
        quotes = raw.count("[인용구]")
        print("인용구: %d, 이미지: %d" % (quotes, raw.count("[이미지]")))
        if quotes < 6:
            fails.append("인용구 %d개 (소제목 4 + 요약 및 정리 + 클로징 = 6개 이상)" % quotes)
        print("전체 글자수(표 포함): %d" % whole)
        if whole < 3000:
            fails.append("전체 %d자 (권장 3000자 이상)" % whole)
    else:
        print("전체 글자수: %d" % whole)
        if total < 1600:
            fails.append("본문 %d자 (최소 1600자)" % total)
        subs = len(re.findall(r"^\s*[1-9]\.\s", raw, re.M))
        print("넘버링 소제목: %d개" % subs)
        if subs != 3:
            fails.append("소제목 %d개 (정확히 3개여야 함)" % subs)
        papers = len(re.findall(r"\[논문\s*\d+\]", raw))
        links = len(re.findall(r"https?://", raw))
        print("논문 인용 블록: %d개, 링크: %d개" % (papers, links))
        if papers < 3:
            fails.append("논문 인용 블록 %d개 (최소 3개)" % papers)
        if links < 3:
            fails.append("논문 링크 %d개 (최소 3개)" % links)
        if args.keyword:
            hits = body_without_title(clean).count(args.keyword)
            print("본문 키워드 '%s': %d회" % (args.keyword, hits))
            if hits != 5:
                fails.append("본문 키워드 %d회 (정확히 5회여야 함)" % hits)
        else:
            print("본문 키워드: --keyword 미지정으로 건너뜀")

    # 주요 단어 과다 반복 (15회 초과)
    words = Counter(w for w in re.findall(r"[가-힣]{2,}", clean) if len(w) >= 3)
    for word, n in words.most_common(10):
        if n > 15:
            fails.append("단어 '%s' %d회 (15회 초과)" % (word, n))

    for word in BANNED_VERBS:
        for m in re.finditer(word, raw):
            ctx = raw[max(0, m.start() - 25):m.start() + 20].replace("\n", " ")
            fails.append("금지 서술어 '%s' — ...%s..." % (word, ctx))

    for word in BANNED_CLAIMS:
        if word in clean:
            fails.append("의료광고 위험 표현 '%s'" % word)

    emoji = {c for c in raw
             if unicodedata.category(c) == "So" and c not in ALLOWED_SYMBOLS}
    if emoji:
        fails.append("본문 이모지 사용: %s" % " ".join(sorted(emoji)))

    if args.emit:
        out = re.sub(r"<</?[^>]+>>\n?", "", raw)
        out = re.sub(r"\n{4,}", "\n\n\n", out).strip() + "\n"
        open(args.emit, "w", encoding="utf-8").write(out)
        print("최종 원고 저장: %s" % args.emit)

    if fails:
        print("\n미충족 %d건" % len(fails))
        for f in fails:
            print("  - %s" % f)
        return 1
    print("\n지침 전 항목 충족")
    return 0


if __name__ == "__main__":
    sys.exit(main())
