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


def parse(path, outdir):
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

    blocks = classify(blocks)
    doc = {
        "source": os.path.basename(path),
        "title_line": blocks[0]["text"] if blocks and blocks[0]["kind"] == "para" else "",
        "blocks": blocks,
    }
    return doc


def classify(blocks):
    """제목·소제목·잠깐 블록을 표시한다. 태그가 없는 원고도 읽기 위함."""
    out = []
    for i, b in enumerate(blocks):
        if b["kind"] == "table":
            flat = " ".join(" ".join(r) for r in b["rows"])
            b["role"] = "잠깐" if "잠깐" in flat else "표"
        elif b["kind"] == "para":
            if i == 0:
                b["role"] = "제목"
            elif NUMBERED.match(b["text"]) and len(b["text"]) <= 60:
                # 넘버링 짧은 줄은 소제목으로 본다. 인용구 태그가 없는 원고 대응
                b["kind"] = "quote"
                b["lines"] = [b["text"]]
                b["role"] = "소제목"
                b.pop("pieces", None)
            else:
                b["role"] = "본문"
        elif b["kind"] == "quote":
            b["role"] = "소제목" if NUMBERED.match(b["lines"][0]) else "인용"
        elif b["kind"] == "image":
            b["role"] = "이미지"
        out.append(b)
    # 소제목 바로 뒤에 이어붙은 짧은 줄을 소제목에 합친다 (두 줄 소제목 대응)
    merged = []
    for b in out:
        if (merged and merged[-1].get("role") == "소제목"
                and b["kind"] == "para" and len(b["text"]) <= 30
                and not NUMBERED.match(b["text"])
                and merged[-1].get("_open", True)):
            merged[-1]["lines"].append(b["text"])
            merged[-1]["_open"] = False
            continue
        if b.get("role") == "소제목":
            b["_open"] = True
        merged.append(b)
    for b in merged:
        b.pop("_open", None)
    return merged


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
    subs = [b for b in doc["blocks"] if b.get("role") == "소제목"]
    for s in subs:
        print("  소제목: %s" % " / ".join(s["lines"])[:70])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--out", required=True, help="작업 디렉터리")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    doc = parse(args.docx, args.out)
    dest = os.path.join(args.out, "doc.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    report(doc)
    print("저장: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
