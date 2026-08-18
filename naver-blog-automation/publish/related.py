#!/usr/bin/env python3
"""'함께 읽으면 좋은 글' 링크를 고른다.

지정한 네이버 블로그의 전체 글 목록을 받아 캐시하고, 원고 주제와 가장
가까운 글을 골라 준다. 링크 출처 블로그는 template.json 의
related_posts_source 로 정한다(두청한의원은 aoske551).

사용:
  python3 related.py index --blog aoske551 --cache work/aoske551.json
  python3 related.py pick  --cache work/aoske551.json --title "왼쪽관자놀이통증 …" --count 2
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

LIST_API = ("https://blog.naver.com/PostTitleListAsync.naver"
            "?blogId={blog}&viewdate=&currentPage={page}"
            "&categoryNo=0&parentCategoryNo=&countPerPage=30")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
STOP = {"방법", "이유", "경우", "때문", "확인", "무엇", "어떻게", "그리고", "하지만",
        "합니다", "입니다", "있습니다", "해야", "위한", "대한", "다면", "라면", "정말"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://blog.naver.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def build_index(blog, cache, max_pages=200):
    """전체 글 목록을 페이지 단위로 받아 캐시한다."""
    posts, seen, page = [], set(), 1
    while page <= max_pages:
        body = fetch(LIST_API.format(blog=blog, page=page))
        # 네이버 응답 JSON 은 이스케이프가 깨져 있어 표준 파서로는 못 읽는다
        pairs = re.findall(r'"logNo":"(\d+)".*?"title":"([^"]*)"', body)
        if not pairs:
            break
        fresh = 0
        for log_no, enc in pairs:
            if log_no in seen:
                continue
            seen.add(log_no)
            title = urllib.parse.unquote_plus(enc).strip()
            posts.append({
                "logNo": log_no,
                "title": title,
                "url": "https://blog.naver.com/%s/%s" % (blog, log_no),
            })
            fresh += 1
        if fresh == 0:
            break
        page += 1
        time.sleep(0.3)
    data = {"blog": blog, "count": len(posts), "posts": posts}
    os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def norm(text):
    """공백·문장부호를 걷어낸 비교용 문자열."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def head_of(keyword):
    """키워드의 증상 어근. '왼쪽관자놀이통증' -> '통증'

    사람이 고른 관련 글을 보면 부위·수식어보다 증상 어근이 먼저 맞아야 한다.
    이게 안 맞으면 '스트레스성두통' 에 '스트레스성 복통' 이 딸려 온다.
    """
    n = norm(keyword)
    for suffix in ("통증", "두통", "저림", "어지럼증", "증상", "실신", "불면",
                   "경련", "마비", "이명", "구토", "복통", "염증"):
        if n.endswith(suffix):
            return suffix
    return n[-2:] if len(n) >= 2 else n


def chunks_of(keyword, lo=2, hi=6):
    n = norm(keyword)
    out = set()
    for size in range(lo, min(hi, len(n)) + 1):
        for i in range(len(n) - size + 1):
            out.add(n[i:i + size])
    return out


def score(keyword, title, extra=""):
    """키워드 적합도. 증상 어근이 없으면 0점으로 떨어뜨린다."""
    nk, nt = norm(keyword), norm(title)
    if not nk or not nt:
        return 0.0
    head = head_of(keyword)
    if head and head not in nt:
        return 0.0
    if nk in nt:                      # 키워드가 제목에 통째로 들어간 경우
        return 1000.0 + len(nk)
    total = 0.0
    for c in chunks_of(keyword):
        if c in nt:
            total = max(total, len(c) ** 2)
    covered = sum(len(c) ** 1.5 for c in chunks_of(keyword, 2, 3) if c in nt)
    bonus = 0.0
    if extra:                         # 제목 나머지 단어로 미세 조정
        ne = norm(extra)
        for w in re.findall(r"[가-힣]{2,}", title):
            if w in ne and w not in STOP:
                bonus += 1.0
    return total + covered * 0.5 + bonus


def pick(cache, keyword, count, title="", exclude=()):
    with open(cache, encoding="utf-8") as f:
        data = json.load(f)
    scored = []
    for p in data["posts"]:
        if p["logNo"] in exclude:
            continue
        s = score(keyword, p["title"], title)
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda x: (-x[0], -int(x[1]["logNo"])))
    return [{"score": round(s, 2), **p} for s, p in scored[:count]]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("index", help="블로그 전체 글 목록 캐시")
    i.add_argument("--blog", required=True)
    i.add_argument("--cache", required=True)

    p = sub.add_parser("pick", help="원고 주제와 가까운 글 고르기")
    p.add_argument("--cache", required=True)
    p.add_argument("--keyword", required=True, help="원고의 메인 키워드")
    p.add_argument("--title", default="", help="원고 제목 (미세 조정용)")
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--json", help="결과를 저장할 경로")

    args = ap.parse_args()
    if args.cmd == "index":
        data = build_index(args.blog, args.cache)
        print("%s — 글 %d개 캐시: %s" % (args.blog, data["count"], args.cache))
    else:
        rows = pick(args.cache, args.keyword, args.count, args.title)
        if not rows:
            print("맞는 글을 찾지 못했습니다. 키워드를 넓혀보세요.")
        for r in rows:
            print("%7.2f  %s\n         %s" % (r["score"], r["title"][:60], r["url"]))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
