#!/usr/bin/env python3
"""DOCX 원고를 발행용 문서 모델(JSON)로 읽는다.

사람이 손으로 뽑은 DOCX를 그대로 받아 블록 단위로 분해한다. 지침이 시키는
두 가지 표기를 모두 읽는다.

  - 실제 워드 표    → table 블록
  - 실제 볼드 서식  → 문장 안의 bold 구간
  - [이미지] 텍스트 → image 슬롯 (사람이 위치만 표시한 자리)
  - 문서에 박힌 사진 → image 슬롯 (파일로 추출)
  - [인용구] 태그   → quote 블록. 태그가 없으면 '1. 소제목' 형태를 인용구로 본다

사용:
  python3 docxparse.py 원고.docx --out work/클리어서울안과-11
"""
import argparse
import json
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W, "a": A, "r": R}

IMG_MARKER = re.compile(r"^\[\s*이미지\s*\]$")
QUOTE_OPEN = re.compile(r"^\[\s*인용구\s*\]$")
QUOTE_CLOSE = re.compile(r"^\[\s*/\s*인용구\s*\]$")
TABLE_OPEN = re.compile(r"^\[\s*표\s*\]$")
TABLE_CLOSE = re.compile(r"^\[\s*/\s*표\s*\]$")
NUMBERED = re.compile(r"^\s*([1-9])\s*\.\s*\S")
TITLE_LABEL = re.compile(r"^\[?\s*제목\s*후보\s*\]?\s*$")
OUTRO_MARK = re.compile(r"^(-+|\[?\s*칼럼을\s*마치며\s*\]?|\[?\s*마무리\s*\]?)$")
OUTRO_CUE = ("오늘 말씀드린", "오늘은", "긴 글", "감사합니다", "감사드립니다",
             "문의 주", "문의주", "마음입니다", "바랍니다")
PART_MARK = re.compile(r"^<</?[^>]+>>$")


def quote_styles(z):
    """styles.xml 에서 인용구 계열 styleId 를 모은다."""
    ids = set()
    try:
        root = ET.fromstring(z.read("word/styles.xml"))
    except KeyError:
        return ids
    for st in root.findall("w:style", NS):
        sid = st.get("{%s}styleId" % W) or ""
        name_el = st.find("w:name", NS)
        name = (name_el.get("{%s}val" % W) if name_el is not None else "") or ""
        blob = (sid + " " + name).lower()
        if "quote" in blob or "인용" in blob:
            ids.add(sid)
    return ids


def style_of(p):
    el = p.find("w:pPr/w:pStyle", NS)
    return el.get("{%s}val" % W) if el is not None else ""


def rels(z):
    """rId -> word/media/... 경로"""
    out = {}
    try:
        root = ET.fromstring(z.read("word/_rels/document.xml.rels"))
    except KeyError:
        return out
    for rel in root:
        rid = rel.get("Id")
        target = rel.get("Target", "")
        if "media" in target:
            out[rid] = "word/" + target.lstrip("/").replace("../", "")
    return out


def runs_of(p, relmap, media_sink):
    """문단을 [{text, bold}] 조각과 이미지 목록으로."""
    pieces, images = [], []
    for r in p.iter("{%s}r" % W):
        if r.find("w:rPr/w:b", NS) is not None:
            bold = True
        else:
            bold = False
        for blip in r.iter("{%s}blip" % A):
            rid = blip.get("{%s}embed" % R)
            path = relmap.get(rid)
            if path:
                images.append(media_sink(path))
        text = ""
        for node in r:
            local = node.tag.split("}")[1]
            if local == "t":
                text += node.text or ""
            elif local in ("br", "cr"):
                text += "\n"
        if not text.strip("\n"):
            if text:
                if pieces:
                    pieces[-1]["text"] += text
            continue
        if pieces and pieces[-1]["bold"] == bold:
            pieces[-1]["text"] += text
        else:
            pieces.append({"text": text, "bold": bold})
    # 앞뒤 공백이 볼드 안에 끌려들어간 경우를 바깥으로 밀어낸다
    for i, piece in enumerate(pieces):
        if not piece["bold"]:
            continue
        stripped = piece["text"].strip()
        if stripped == piece["text"] or not stripped:
            continue
        lead = piece["text"][:len(piece["text"]) - len(piece["text"].lstrip())]
        tail = piece["text"][len(piece["text"].rstrip()):]
        piece["text"] = stripped
        if lead and i > 0 and not pieces[i - 1]["bold"]:
            pieces[i - 1]["text"] += lead
        if tail and i + 1 < len(pieces) and not pieces[i + 1]["bold"]:
            pieces[i + 1]["text"] = tail + pieces[i + 1]["text"]
    return pieces, images


def plain(pieces):
    return "".join(p["text"] for p in pieces).strip()


def cell_text(tc):
    return "\n".join(
        "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
        for p in tc.findall("w:p", NS)
    ).strip()


def read_table(tbl):
    rows = []
    for tr in tbl.findall("w:tr", NS):
        rows.append([cell_text(tc) for tc in tr.findall("w:tc", NS)])
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return rows


def parse(path, outdir, heading_lines=1):
    z = zipfile.ZipFile(path)
    relmap = rels(z)
    mediadir = os.path.join(outdir, "media")
    os.makedirs(mediadir, exist_ok=True)
    seen = {}

    def media_sink(zpath):
        if zpath in seen:
            return seen[zpath]
        name = "doc_%02d_%s" % (len(seen) + 1, os.path.basename(zpath))
        dest = os.path.join(mediadir, name)
        with open(dest, "wb") as f:
            f.write(z.read(zpath))
        seen[zpath] = os.path.relpath(dest, outdir)
        return seen[zpath]

    qstyles = quote_styles(z)
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find("w:body", NS)

    blocks = []
    quote_buf = None
    table_buf = None

    for el in body:
        tag = el.tag.split("}")[1]

        if tag == "tbl":
            blocks.append({"kind": "table", "rows": read_table(el)})
            continue
        if tag != "p":
            continue

        pieces, imgs = runs_of(el, relmap, media_sink)
        for src in imgs:
            blocks.append({"kind": "image", "source": "embedded", "file": src})
        text = plain(pieces)
        if not text:
            continue

        if PART_MARK.match(text):          # <<서론>> 같은 검증용 마커는 버린다
            continue
        if IMG_MARKER.match(text):
            blocks.append({"kind": "image", "source": "slot", "file": None})
            continue

        if TABLE_OPEN.match(text):
            table_buf = []
            continue
        if TABLE_CLOSE.match(text):
            if table_buf:
                rows = [[c.strip() for c in ln.split("|")] for ln in table_buf]
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                blocks.append({"kind": "table", "rows": rows})
            table_buf = None
            continue
        if table_buf is not None:
            table_buf.append(text)
            continue

        if QUOTE_OPEN.match(text):
            quote_buf = []
            continue
        if QUOTE_CLOSE.match(text):
            if quote_buf:
                blocks.append({"kind": "quote", "lines": quote_buf})
            quote_buf = None
            continue
        if quote_buf is not None:
            quote_buf.append(text)
            continue

        if style_of(el) in qstyles:
            blocks.append({"kind": "quote", "lines": text.split("\n")})
            continue

        blocks.append({"kind": "para", "pieces": pieces, "text": text})

    blocks = classify(blocks, heading_lines)
    cands = [b for b in blocks if b.get("role") == "제목후보"]
    doc = {
        "source": os.path.basename(path),
        "title_candidates": [b["lines"][0] if b["kind"] == "quote" else b["text"]
                             for b in cands],
        "title_line": blocks[0]["text"] if blocks and blocks[0]["kind"] == "para" else "",
        "blocks": blocks,
    }
    return doc


def classify(blocks, heading_lines=1):
    """제목 후보·소제목·잠깐 블록을 구분하고 섹션을 나눈다.

    heading_lines 는 소제목이 몇 줄짜리인지다. 고객사 템플릿마다 다르다.
    두청한의원은 한 줄이라 뒤따르는 본문 첫 문장을 붙이면 안 된다.
    """
    out = []
    in_candidates = False
    for i, b in enumerate(blocks):
        if b["kind"] == "table":
            flat = " ".join(" ".join(r) for r in b["rows"])
            b["role"] = "잠깐" if "잠깐" in flat else "표"
            in_candidates = False
        elif b["kind"] == "para":
            text = b["text"]
            if TITLE_LABEL.match(text):
                b["role"] = "제목후보라벨"
                in_candidates = True
            elif in_candidates and NUMBERED.match(text):
                b["role"] = "제목후보"
            elif i == 0:
                b["role"] = "제목"
                in_candidates = False
            elif NUMBERED.match(text) and len(text) <= 60:
                b["kind"] = "quote"
                b["lines"] = [text]
                b["role"] = "소제목"
                b.pop("pieces", None)
                in_candidates = False
            else:
                b["role"] = "본문"
                in_candidates = False
        elif b["kind"] == "quote":
            first = b["lines"][0]
            if TITLE_LABEL.match(first):
                b["role"] = "제목후보라벨"
                in_candidates = True
            elif in_candidates and NUMBERED.match(first):
                b["role"] = "제목후보"
            elif NUMBERED.match(first):
                b["role"] = "소제목"
                in_candidates = False
            else:
                b["role"] = "인용"
                in_candidates = False
        elif b["kind"] == "image":
            b["role"] = "이미지"
        out.append(b)

    out = split_overlong_headings(out, heading_lines)
    assign_sections(out)
    return out


def split_overlong_headings(blocks, heading_lines):
    """소제목 블록이 정해진 줄 수보다 길면 나머지를 본문으로 되돌린다."""
    fixed = []
    for b in blocks:
        if b.get("role") in ("소제목", "제목후보") and b["kind"] == "quote" \
                and len(b["lines"]) > heading_lines:
            keep, rest = b["lines"][:heading_lines], b["lines"][heading_lines:]
            b["lines"] = keep
            fixed.append(b)
            for line in rest:
                fixed.append({"kind": "para", "role": "본문", "text": line,
                              "pieces": [{"text": line, "bold": False}]})
        else:
            fixed.append(b)
    return fixed


def assign_sections(blocks):
    """블록마다 어느 파트인지 표시한다. plan 단계에서 이미지 배치에 쓴다."""
    section, n = "머리말", 0
    outro_at = find_outro(blocks)
    for i, b in enumerate(blocks):
        if outro_at is not None and i >= outro_at:
            b["section"] = "마무리"
            continue
        if b.get("role") in ("제목", "제목후보라벨", "제목후보"):
            b["section"] = "제목"
            continue
        if b.get("role") == "소제목":
            n += 1
            section = "소제목%d" % n
        elif section == "머리말" and b.get("role") == "본문":
            section = "서론"
        b["section"] = section


def find_outro(blocks):
    """마무리가 시작되는 인덱스. 마커가 있으면 그것을, 없으면 단서로 찾는다."""
    for i, b in enumerate(blocks):
        if b["kind"] == "para" and OUTRO_MARK.match(b["text"].strip()):
            return i
    last_heading = max((i for i, b in enumerate(blocks)
                        if b.get("role") == "소제목"), default=None)
    if last_heading is None:
        return None
    tail_start = max(last_heading + 1, int(len(blocks) * 0.7))
    for i in range(tail_start, len(blocks)):
        b = blocks[i]
        if b["kind"] == "para" and any(c in b["text"] for c in OUTRO_CUE):
            return i
    return None


def report(doc):
    counts = {}
    for b in doc["blocks"]:
        key = b.get("role", b["kind"])
        counts[key] = counts.get(key, 0) + 1
    print("원본: %s" % doc["source"])
    print("제목: %s" % doc["title_line"][:70])
    print("블록 %d개 — %s" % (len(doc["blocks"]),
                            ", ".join("%s %d" % kv for kv in sorted(counts.items()))))
    slots = sum(1 for b in doc["blocks"]
                if b["kind"] == "image" and b["source"] == "slot")
    embedded = sum(1 for b in doc["blocks"]
                   if b["kind"] == "image" and b["source"] == "embedded")
    print("이미지 — 빈 슬롯 %d개, 문서에 박힌 것 %d개" % (slots, embedded))
    if doc.get("title_candidates"):
        print("제목 후보 %d개" % len(doc["title_candidates"]))
        for c in doc["title_candidates"]:
            print("  · %s" % c[:70])
    subs = [b for b in doc["blocks"] if b.get("role") == "소제목"]
    for sb in subs:
        print("  소제목: %s" % " / ".join(sb["lines"])[:70])
    order, seen = [], set()
    for b in doc["blocks"]:
        sec = b.get("section")
        if sec and sec not in seen:
            seen.add(sec)
            order.append(sec)
    print("파트 구성: %s" % " → ".join(order))
    if "마무리" not in seen:
        print("  ! 마무리 경계를 못 찾았습니다. 원고에 '-' 한 줄을 넣어주시면 확실해집니다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--out", required=True, help="작업 디렉터리")
    ap.add_argument("--heading-lines", type=int, default=1,
                    help="소제목이 몇 줄인지 (두청한의원 1줄)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    doc = parse(args.docx, args.out, args.heading_lines)
    dest = os.path.join(args.out, "doc.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    report(doc)
    print("저장: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
