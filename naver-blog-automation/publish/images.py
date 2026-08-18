#!/usr/bin/env python3
"""이미지 슬롯에 사진을 채운다.

고객사가 준 내부 사진을 먼저 쓰고, 남는 자리만 무료 라이선스 스톡에서 받는다.
내부 사진은 파일명만으로는 무엇이 찍혔는지 알 수 없으므로, 한 번 카탈로그를
만들어 두고 사람(또는 에이전트)이 사진을 열어 설명을 채운다. 그 설명이
슬롯 문맥과 맞춰지는 기준이 된다.

사용:
  python3 images.py catalog --dir "C:/.../사진" --out catalog.json
  python3 images.py caption --catalog catalog.json --file 연출/DSC_0012.jpg --text "상담 장면"
  python3 images.py todo    --catalog catalog.json
  python3 images.py assign  --plan plan.json --catalog catalog.json --out assign.json
  python3 images.py stock   --assign assign.json --out media/ [--provider openverse]
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# 원고 문맥 → 사진에서 찾을 말. 진료 콘텐츠에서 반복되는 축만 넣었다.
SYNONYM = {
    "상담": ["상담", "설명", "진료", "면담", "대화", "마주"],
    "검사": ["검사", "측정", "장비", "뇌파", "체열", "자율신경", "헤드셋", "모니터"],
    "촉진": ["촉진", "목", "어깨", "만지", "짚", "자세", "경추"],
    "치료": ["치료", "침", "약침", "한약", "시술"],
    "원장": ["원장", "의사", "한의사", "인물"],
    "내원": ["대기", "접수", "인테리어", "입구", "실내", "복도"],
}
STOP = {"있습니다", "합니다", "때문", "경우", "이런", "그런", "위해", "대해"}

# 축 → 스톡 검색어. 한국어 문맥을 그대로 넣으면 결과가 안 나온다.
STOCK_QUERY = {
    "상담": "doctor consultation patient clinic",
    "검사": "medical examination equipment diagnostic",
    "촉진": "neck shoulder physical examination",
    "치료": "acupuncture treatment clinic",
    "원장": "doctor portrait white coat",
    "내원": "clinic interior waiting room",
}
DEFAULT_QUERY = "clinic doctor patient consultation"

OPENVERSE = ("https://api.openverse.org/v1/images/"
             "?q={q}&page_size=8&license_type=commercial&mature=false")
UA = "naver-blog-automation/1.0"


def walk(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.lower().endswith(EXT):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            out.append({"file": rel, "folder": os.path.dirname(rel) or ".",
                        "bytes": size, "caption": None, "used": 0})
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def tokens(text):
    words = re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", text or "")
    return {w for w in words if w not in STOP}


def axes(text):
    """문장이 어떤 축(상담·검사·촉진…)에 걸리는지."""
    t = text or ""
    hit = set()
    for axis, words in SYNONYM.items():
        if any(w in t for w in words):
            hit.add(axis)
    return hit


def match_score(slot, photo):
    cap = photo.get("caption") or ""
    if not cap:
        return 0.0
    ctx = "%s %s" % (slot.get("heading", ""), slot.get("context", ""))
    if slot["slot"].startswith("머리"):
        # 인사말 직후 자리는 본문 문맥보다 화자·공간을 보여주는 사진이 맞는다
        return (10.0 if axes(cap) & {"원장", "상담", "내원"} else 0.0) \
            + (2.0 if photo.get("folder", "").startswith("연출") else 0.0) \
            - photo.get("used", 0) * 100.0
    score = len(axes(ctx) & axes(cap)) * 10.0
    score += len(tokens(ctx) & tokens(cap)) * 1.5
    if photo.get("folder", "").startswith("연출"):
        score += 1.0                      # 연출 폴더를 기본으로 쓴다고 하셨다
    score -= photo.get("used", 0) * 100.0  # 한 글에서 같은 사진을 두 번 쓰지 않는다
    return score


def cmd_catalog(args):
    if not os.path.isdir(args.dir):
        print("폴더를 찾을 수 없습니다: %s" % args.dir, file=sys.stderr)
        print("이 스크립트는 사진이 있는 PC에서 실행하셔야 합니다.", file=sys.stderr)
        return 1
    photos = walk(args.dir)
    old = {p["file"]: p for p in (load(args.out).get("photos", [])
                                  if os.path.exists(args.out) else [])}
    for p in photos:                       # 기존 설명은 지우지 않는다
        if p["file"] in old:
            p["caption"] = old[p["file"]]["caption"]
    save(args.out, {"root": os.path.abspath(args.dir), "photos": photos})
    done = sum(1 for p in photos if p["caption"])
    print("사진 %d장 (설명 있음 %d, 없음 %d) → %s"
          % (len(photos), done, len(photos) - done, args.out))
    folders = {}
    for p in photos:
        folders[p["folder"]] = folders.get(p["folder"], 0) + 1
    for f, n in sorted(folders.items()):
        print("  %-24s %d장" % (f, n))
    return 0


def cmd_caption(args):
    data = load(args.catalog)
    for p in data["photos"]:
        if p["file"] == args.file:
            p["caption"] = args.text
            save(args.catalog, data)
            print("설명 저장: %s" % args.file)
            return 0
    print("카탈로그에 없는 파일: %s" % args.file, file=sys.stderr)
    return 1


def cmd_todo(args):
    data = load(args.catalog)
    todo = [p for p in data["photos"] if not p["caption"]]
    print("설명이 필요한 사진 %d장" % len(todo))
    for p in todo[:args.limit]:
        print("  %s" % os.path.join(data["root"], p["file"]))
    if len(todo) > args.limit:
        print("  ... 외 %d장" % (len(todo) - args.limit))
    return 0


def cmd_assign(args):
    plan = load(args.plan)
    data = load(args.catalog) if args.catalog and os.path.exists(args.catalog) \
        else {"root": "", "photos": []}
    photos = data["photos"]

    result, unmatched = [], []
    for slot in plan["image_slots"]:
        best, best_score = None, args.threshold
        for p in photos:
            s = match_score(slot, p)
            if s > best_score:
                best, best_score = p, s
        if best:
            best["used"] = best.get("used", 0) + 1
            result.append({"slot": slot["slot"], "source": "client_internal",
                           "file": os.path.join(data["root"], best["file"]),
                           "caption": best["caption"],
                           "score": round(best_score, 1),
                           "context": slot["context"]})
        else:
            hit = axes("%s %s" % (slot.get("heading", ""), slot.get("context", "")))
            query = " ".join(STOCK_QUERY[a] for a in sorted(hit)) or DEFAULT_QUERY
            unmatched.append({"slot": slot["slot"], "source": "free_stock",
                              "query": query, "context": slot["context"],
                              "file": None})
            result.append(unmatched[-1])

    for p in photos:
        p["used"] = 0
    save(args.catalog, data) if args.catalog and os.path.exists(args.catalog) else None
    save(args.out, {"title": plan.get("title"), "slots": result})

    print("슬롯 %d개 — 내부 사진 %d, 스톡 필요 %d"
          % (len(result), len(result) - len(unmatched), len(unmatched)))
    for r in result:
        if r["source"] == "client_internal":
            print("  %-12s %s  (%s)" % (r["slot"], os.path.basename(r["file"]),
                                        (r["caption"] or "")[:34]))
        else:
            print("  %-12s [스톡 필요] 검색어: %s" % (r["slot"], r["query"]))
    print("저장: %s" % args.out)
    return 0


def cmd_stock(args):
    data = load(args.assign)
    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for s in data["slots"]:
        if s["source"] != "free_stock" or s.get("file"):
            continue
        url = OPENVERSE.format(q=urllib.parse.quote(s["query"]))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                hits = json.loads(r.read().decode()).get("results", [])
        except Exception as e:
            print("  %s 검색 실패: %s" % (s["slot"], e), file=sys.stderr)
            continue
        if not hits:
            print("  %s 결과 없음 (검색어: %s)" % (s["slot"], s["query"]))
            continue
        top = hits[0]
        dest = os.path.join(args.out, "%s.jpg" % s["slot"])
        try:
            req = urllib.request.Request(top["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                f.write(r.read())
        except Exception as e:
            print("  %s 내려받기 실패: %s" % (s["slot"], e), file=sys.stderr)
            continue
        s["file"] = dest
        manifest.append({"slot": s["slot"], "file": dest,
                         "source_url": top.get("foreign_landing_url") or top.get("url"),
                         "license": top.get("license"),
                         "license_url": top.get("license_url"),
                         "creator": top.get("creator"),
                         "title": top.get("title")})
        print("  %s ← %s (%s)" % (s["slot"], top.get("title", "")[:40], top.get("license")))

    save(args.assign, data)
    if manifest:
        mpath = os.path.join(args.out, "manifest.json")
        save(mpath, manifest)
        print("출처·라이선스 기록: %s" % mpath)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalog", help="사진 폴더를 훑어 카탈로그 생성")
    c.add_argument("--dir", required=True)
    c.add_argument("--out", required=True)

    p = sub.add_parser("caption", help="사진 한 장에 설명 달기")
    p.add_argument("--catalog", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--text", required=True)

    t = sub.add_parser("todo", help="설명이 아직 없는 사진 목록")
    t.add_argument("--catalog", required=True)
    t.add_argument("--limit", type=int, default=30)

    a = sub.add_parser("assign", help="슬롯에 사진 배정")
    a.add_argument("--plan", required=True)
    a.add_argument("--catalog")
    a.add_argument("--out", required=True)
    a.add_argument("--threshold", type=float, default=3.0)

    s = sub.add_parser("stock", help="남은 슬롯을 무료 라이선스 스톡으로 채움")
    s.add_argument("--assign", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--provider", default="openverse")

    args = ap.parse_args()
    return {"catalog": cmd_catalog, "caption": cmd_caption, "todo": cmd_todo,
            "assign": cmd_assign, "stock": cmd_stock}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
