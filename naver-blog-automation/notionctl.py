#!/usr/bin/env python3
"""네이버 브랜드블로그 원고 자동화 — 노션 REST 클라이언트.

Claude의 Notion MCP 커넥터는 승인한 워크스페이스 하나만 볼 수 있다.
프리랜서 워크스페이스는 그 밖이므로, 노션 내부 통합(Internal Integration)
토큰으로 REST API를 직접 호출한다.

준비:
  1. notion.so/my-integrations 에서 내부 통합 생성 → 시크릿 복사
  2. 대상 플래너 페이지 ⋯ → 연결 → 그 통합 추가
  3. 환경변수 NOTION_TOKEN 에 시크릿 저장 (새 세션에서 반영됨)

사용:
  python3 notionctl.py check
  python3 notionctl.py find-planner [검색어]
  python3 notionctl.py schema <db_id>
  python3 notionctl.py list  --client 클리어서울안과 [--json work.json]
  python3 notionctl.py write --page <page_id> --body 원고.txt [--status "원고 저장 완료"]
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


class NotionError(RuntimeError):
    pass


def token():
    t = os.environ.get("NOTION_TOKEN", "").strip()
    if not t:
        raise NotionError(
            "환경변수 NOTION_TOKEN 이 비어 있습니다.\n"
            "claude.ai/code 환경 설정에 저장한 뒤 새 세션에서 다시 실행하세요."
        )
    return t


def call(method, path, payload=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token())
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body).get("message", body)
        except ValueError:
            msg = body
        if e.code == 401:
            msg += "\n→ 토큰이 잘못되었거나 만료되었습니다."
        elif e.code == 404:
            msg += ("\n→ 통합이 그 페이지에 연결되어 있지 않습니다. "
                    "노션에서 페이지 ⋯ → 연결 → 통합 추가를 확인하세요.")
        raise NotionError("HTTP %d %s\n%s" % (e.code, path, msg))
    except urllib.error.URLError as e:
        raise NotionError(
            "api.notion.com 에 연결하지 못했습니다 (%s).\n"
            "환경의 허용 도메인에 api.notion.com 이 있는지 확인하세요." % e.reason)


def paged(path, payload):
    out, cursor = [], None
    while True:
        body = dict(payload)
        if cursor:
            body["start_cursor"] = cursor
        res = call("POST", path, body)
        out.extend(res.get("results", []))
        if not res.get("has_more"):
            return out
        cursor = res.get("next_cursor")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def client_config(name):
    for c in load_config()["clients"]:
        if c["name"] == name or c["slug"] == name:
            return c
    raise NotionError("config.json 에 '%s' 고객사가 없습니다." % name)


# ---------------------------------------------------------------- 속성 읽기

def plain(prop):
    """rich_text / title 속성을 평문으로."""
    if not prop:
        return ""
    items = prop.get("rich_text") or prop.get("title") or []
    return "".join(i.get("plain_text", "") for i in items).strip()


def people_names(prop):
    return [p.get("name", "") for p in (prop or {}).get("people", [])]


def status_name(prop):
    node = (prop or {}).get("status") or (prop or {}).get("select")
    return (node or {}).get("name", "")


def select_name(prop):
    node = (prop or {}).get("select") or (prop or {}).get("status")
    return (node or {}).get("name", "")


# ---------------------------------------------------------------- 마커 → 블록

BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def rich(text):
    """**볼드** 를 Notion rich_text 배열로."""
    out, pos = [], 0
    for m in BOLD.finditer(text):
        if m.start() > pos:
            out.append({"type": "text", "text": {"content": text[pos:m.start()]}})
        out.append({"type": "text", "text": {"content": m.group(1)},
                    "annotations": {"bold": True}})
        pos = m.end()
    if pos < len(text):
        out.append({"type": "text", "text": {"content": text[pos:]}})
    if not out:
        out = [{"type": "text", "text": {"content": ""}}]
    # Notion 은 rich_text 항목당 2000자 제한
    split = []
    for item in out:
        content = item["text"]["content"]
        while len(content) > 2000:
            piece = dict(item)
            piece["text"] = dict(item["text"], content=content[:2000])
            split.append(piece)
            content = content[2000:]
        item["text"] = dict(item["text"], content=content)
        split.append(item)
    return split


def para(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich(text)}}


def quote(text):
    return {"object": "block", "type": "quote",
            "quote": {"rich_text": rich(text)}}


def table(lines):
    rows = [[c.strip() for c in ln.split("|")] for ln in lines]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = width > 1 and rows[0][0] in ("구분", "항목", "단계")
    return {"object": "block", "type": "table", "table": {
        "table_width": width,
        "has_column_header": header,
        "has_row_header": False,
        "children": [
            {"object": "block", "type": "table_row",
             "table_row": {"cells": [rich(c) for c in r]}}
            for r in rows
        ],
    }}


def to_blocks(text):
    """[표]/[인용구]/[이미지]/**볼드** 마커가 붙은 원고를 Notion 블록으로."""
    blocks, buf, mode = [], [], None
    for line in text.splitlines():
        s = line.strip()
        if s == "[표]":
            mode, buf = "table", []
            continue
        if s == "[인용구]":
            mode, buf = "quote", []
            continue
        if s in ("[/표]", "[/인용구]"):
            if mode == "table" and buf:
                blocks.append(table(buf))
            elif mode == "quote" and buf:
                blocks.append(quote("\n".join(buf)))
            mode, buf = None, []
            continue
        if mode:
            if s:
                buf.append(s)
            continue
        if s:
            blocks.append(para(s))
    return blocks


# ---------------------------------------------------------------- 명령

def cmd_check(args):
    me = call("GET", "/users/me")
    print("토큰 정상. 통합 이름: %s" % me.get("name", "(이름 없음)"))
    res = call("POST", "/search", {"page_size": 20})
    hits = res.get("results", [])
    print("이 통합이 접근 가능한 항목: %d개" % len(hits))
    for h in hits:
        title = ""
        if h["object"] == "database":
            title = "".join(t.get("plain_text", "") for t in h.get("title", []))
        else:
            for v in h.get("properties", {}).values():
                if v.get("type") == "title":
                    title = plain(v)
                    break
        print("  [%s] %s  %s" % (h["object"], title or "(제목 없음)", h["id"]))
    if not hits:
        print("\n접근 가능한 항목이 없습니다.")
        print("노션에서 플래너 페이지 ⋯ → 연결 → 통합을 추가했는지 확인하세요.")
    return 0


def cmd_find_planner(args):
    payload = {"filter": {"property": "object", "value": "database"}, "page_size": 50}
    if args.query:
        payload["query"] = args.query
    for db in paged("/search", payload):
        title = "".join(t.get("plain_text", "") for t in db.get("title", []))
        print("%s  %s" % (db["id"], title or "(제목 없음)"))
        print("   속성: %s" % ", ".join(db.get("properties", {}).keys()))
    return 0


def cmd_schema(args):
    db = call("GET", "/databases/" + args.db_id)
    title = "".join(t.get("plain_text", "") for t in db.get("title", []))
    print("DB: %s (%s)\n" % (title, db["id"]))
    for name, spec in db.get("properties", {}).items():
        kind = spec["type"]
        extra = ""
        if kind in ("select", "status", "multi_select"):
            node = spec[kind]
            opts = node.get("options", [])
            extra = " → " + ", ".join(o["name"] for o in opts)
        print("  %-14s %-12s%s" % (name, kind, extra))
    return 0


def cmd_list(args):
    cfg = client_config(args.client)
    p = cfg["properties"]
    rows = paged("/databases/%s/query" % cfg["planner_db_id"], {"page_size": 100})

    targets, skipped = [], []
    for row in rows:
        props = row.get("properties", {})
        title = plain(props.get(p["title"]))
        keyword = plain(props.get(p["keyword"]))
        status = status_name(props.get(p["status"]))
        kind = select_name(props.get(p["kind"]))
        owners = people_names(props.get(p["assignee"]))

        reasons = []
        if cfg["assignee"] not in owners:
            reasons.append("담당자 불일치(%s)" % (", ".join(owners) or "없음"))
        if not keyword:
            reasons.append("키워드 없음")
        if status != cfg["trigger_status"]:
            reasons.append("진행 상황 '%s'" % (status or "없음"))
        if kind not in cfg["guidelines"]:
            reasons.append("지침 없는 종류 '%s'" % (kind or "없음"))
        if "템플릿" in title:
            reasons.append("템플릿 행")

        item = {"page_id": row["id"], "title": title, "keyword": keyword,
                "kind": kind, "status": status, "url": row.get("url", "")}
        if reasons:
            item["reasons"] = reasons
            skipped.append(item)
        else:
            item["guideline"] = cfg["guidelines"][kind]
            targets.append(item)

    limit = cfg.get("max_per_run") or len(targets)
    waiting = targets[limit:]
    targets = targets[:limit]

    result = {"client": cfg["name"], "targets": targets,
              "waiting": waiting, "skipped": skipped}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("작업 목록 저장: %s" % args.json)

    print("전체 %d행 / 대상 %d건 / 대기 %d건 / 제외 %d건\n"
          % (len(rows), len(targets), len(waiting), len(skipped)))
    for t in targets:
        print("  대상  %-22s %-8s %s" % (t["title"], t["kind"], t["keyword"]))
    for t in waiting:
        print("  대기  %-22s %-8s %s" % (t["title"], t["kind"], t["keyword"]))
    if args.verbose:
        for s in skipped:
            print("  제외  %-22s %s" % (s["title"], "; ".join(s["reasons"])))
    return 0


def cmd_write(args):
    with open(args.body, encoding="utf-8") as f:
        blocks = to_blocks(f.read())
    if not blocks:
        raise NotionError("원고에서 블록을 만들지 못했습니다: %s" % args.body)

    if args.divider:
        blocks.insert(0, {"object": "block", "type": "divider", "divider": {}})

    # 본문 끝에 추가만 한다. 기존 블록은 건드리지 않는다.
    for i in range(0, len(blocks), 100):
        call("PATCH", "/blocks/%s/children" % args.page,
             {"children": blocks[i:i + 100]})
    print("원고 삽입 완료: %d블록" % len(blocks))

    if args.status:
        cfg = client_config(args.client) if args.client else None
        prop = cfg["properties"]["status"] if cfg else "진행 상황"
        call("PATCH", "/pages/" + args.page,
             {"properties": {prop: {"status": {"name": args.status}}}})
        print("진행 상황 변경: %s" % args.status)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="토큰과 접근 권한 확인")

    f = sub.add_parser("find-planner", help="접근 가능한 데이터베이스 목록")
    f.add_argument("query", nargs="?", default="")

    s = sub.add_parser("schema", help="DB 속성과 선택지 출력")
    s.add_argument("db_id")

    l = sub.add_parser("list", help="작업 대상 행 추출")
    l.add_argument("--client", required=True)
    l.add_argument("--json", help="작업 목록을 저장할 경로")
    l.add_argument("--verbose", action="store_true", help="제외된 행의 사유까지 출력")

    w = sub.add_parser("write", help="행 페이지에 원고 삽입 + 상태 변경")
    w.add_argument("--page", required=True)
    w.add_argument("--body", required=True)
    w.add_argument("--status", help="삽입 성공 시 바꿀 진행 상황")
    w.add_argument("--client", help="속성명을 config.json 에서 읽을 고객사")
    w.add_argument("--divider", action="store_true", help="원고 앞에 구분선 추가")

    args = ap.parse_args()
    handlers = {"check": cmd_check, "find-planner": cmd_find_planner,
                "schema": cmd_schema, "list": cmd_list, "write": cmd_write}
    try:
        return handlers[args.cmd](args)
    except NotionError as e:
        print("오류: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
