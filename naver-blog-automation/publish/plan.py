#!/usr/bin/env python3
"""파싱한 원고를 고객사 템플릿 순서에 배치한다.

doc.json + template.json → plan.json
plan.json 은 스마트에디터에 넣을 컴포넌트를 순서대로 나열한 것이며,
이미지 슬롯에는 '여기 어떤 그림이 필요한지'를 함께 적어 둔다.
실제 파일은 images.py 가 채운다.

사용:
  python3 plan.py --doc work/doc.json --template clients/ducheong/template.json \
      --keyword 3차신경통 --related work/related.json --out work/plan.json
"""
import argparse
import json
import os
import re
import sys

# 소제목 파트별로 이미지를 몇 장 넣을지. 발행글 2건 실측값(총 5~6장) 기준.
IMAGES_PER_SECTION = {"서론": 1, "소제목1": 2, "소제목2": 1, "소제목3": 2}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def section_blocks(doc, name):
    return [b for b in doc["blocks"] if b.get("section") == name]


def body_text(blocks):
    """본문 문단만 순서대로. 볼드 정보는 유지한다."""
    out = []
    for b in blocks:
        if b["kind"] == "para" and b.get("role") == "본문":
            out.append({"text": b["text"], "pieces": b.get("pieces", [])})
    return out


def heading_of(doc, name):
    for b in doc["blocks"]:
        if b.get("section") == name and b.get("role") == "소제목":
            return b["lines"][0]
    return ""


def tables_of(doc, name):
    return [b["rows"] for b in doc["blocks"]
            if b.get("section") == name and b.get("role") == "표"]


def image_brief(section, heading, paras, index):
    """이 자리에 어떤 그림이 와야 하는지 한 줄로. images.py 의 검색어가 된다."""
    near = paras[min(index, len(paras) - 1)]["text"] if paras else heading
    near = re.sub(r"\s+", " ", near)[:60]
    return {
        "section": section,
        "heading": heading,
        "context": near,
        "hint": "이 문단이 말하는 장면. 인물 클로즈업보다 상황·부위·검사 장면이 맞는다",
    }


def section_stream(doc, name):
    """파트 안의 본문 문단과 표를 원문 순서 그대로 뽑는다."""
    stream = []
    for b in doc["blocks"]:
        if b.get("section") != name:
            continue
        if b["kind"] == "para" and b.get("role") == "본문":
            stream.append({"type": "para", "text": b["text"],
                           "pieces": b.get("pieces", [])})
        elif b.get("role") == "표":
            stream.append({"type": "table", "rows": b["rows"]})
    return stream


def interleave(stream, n_images, section, heading):
    """원문 순서를 지키면서 문단 사이에만 이미지 슬롯을 끼운다.

    표는 앞 문장이 '아래 표는...' 처럼 도입하는 경우가 많아 위치를 옮기지 않는다.
    이미지도 표 바로 앞에는 넣지 않는다.
    """
    paras = [i for i, x in enumerate(stream) if x["type"] == "para"]
    slots, cuts = [], []
    if n_images > 0 and len(paras) > 1:
        step = max(1, len(paras) // (n_images + 1))
        for k in range(n_images):
            idx = min(step * (k + 1), len(paras) - 1)
            pos = paras[idx]
            if pos + 1 < len(stream) and stream[pos]["type"] == "para" \
                    and stream[min(pos + 1, len(stream) - 1)]["type"] == "table":
                pos -= 1                      # 표 도입 문장과 표 사이를 벌리지 않는다
            if pos > 0 and pos not in cuts:
                cuts.append(pos)
    cuts = sorted(set(cuts))

    items, buf, k = [], [], 0
    for i, x in enumerate(stream):
        if i in cuts and buf:
            items.append({"type": "text", "paras": buf})
            buf = []
            k += 1
            name = "%s_%d" % (section, k)
            brief = image_brief(section, heading,
                                [p for p in stream if p["type"] == "para"], i)
            items.append({"type": "image", "slot": name, "brief": brief})
            slots.append({"slot": name, **brief})
        if x["type"] == "para":
            buf.append({"text": x["text"], "pieces": x["pieces"]})
        else:
            if buf:
                items.append({"type": "text", "paras": buf})
                buf = []
            items.append({"type": "table", "rows": x["rows"]})
    if buf:
        items.append({"type": "text", "paras": buf})
    return items, slots


def build(doc, tpl, keyword, related, title=None):
    cands = doc.get("title_candidates") or []
    chosen = title or (re.sub(r"^\s*\d+\.\s*", "", cands[0]) if cands else doc.get("title_line", ""))

    intro = body_text(section_blocks(doc, "서론"))
    outro = body_text(section_blocks(doc, "마무리"))
    heads = [heading_of(doc, "소제목%d" % i) for i in (1, 2, 3)]

    blocks, slots = [], []

    blocks.append({"component": "quotation", "role": "제목 인용구",
                   "align": "center", "text": chosen})

    toc_rows = [["목차"]] + [[h] for h in heads if h]
    blocks.append({"component": "table", "role": "목차",
                   "align": "center", "rows": toc_rows})

    greeting = next((b for b in tpl["structure"] if b.get("role") == "인사말"), {})
    blocks.append({"component": "text", "role": "인사말", "fixed": True,
                   "text": greeting.get("text", "")})

    # 인사말 직후 이미지 1장은 템플릿 고정 위치다
    blocks.append({"component": "image", "role": "인사말 직후",
                   "slot": "머리_1",
                   "brief": image_brief("머리", chosen, intro, 0)})
    slots.append({"slot": "머리_1", **image_brief("머리", chosen, intro, 0)})
    blocks.append({"component": "text", "role": "서론",
                   "paras": intro})
    blocks.append({"component": "horizontalLine", "role": "서론 끝"})

    for i in (1, 2, 3):
        name = "소제목%d" % i
        head = heads[i - 1]
        blocks.append({"component": "quotation", "role": name, "text": head})
        items, s = interleave(section_stream(doc, name),
                              IMAGES_PER_SECTION[name], name, head)
        for it in items:
            if it["type"] == "text":
                if it["paras"]:
                    blocks.append({"component": "text", "role": "%s 본문" % name,
                                   "paras": it["paras"]})
            elif it["type"] == "table":
                blocks.append({"component": "table", "role": "%s 표" % name,
                               "rows": it["rows"], "has_header": True})
            else:
                blocks.append({"component": "image", "role": "%s 이미지" % name,
                               "slot": it["slot"], "brief": it["brief"]})
        slots.extend(s)

    blocks.append({"component": "horizontalLine", "role": "마무리 앞"})
    blocks.append({"component": "text", "role": "마무리", "compose": {
        "label": {"text": "[칼럼을 마치며]", "highlight": tpl["style"]["highlight_color"],
                  "bold": True},
        "paras": outro,
        "thanks": "긴 글 함께해주셔서 감사드립니다.",
        "signature": {"text": "두청한의원\n원장 김도환 드림", "align": "right"},
    }})

    blocks.append({"component": "horizontalLine", "role": "관련 글 앞"})
    blocks.append({"component": "text", "role": "관련 글 라벨", "align": "center",
                   "text": "[함께 읽으면 좋은 글]",
                   "highlight": tpl["style"]["highlight_color"], "bold": True})
    for r in related:
        blocks.append({"component": "oglink", "role": "관련 글",
                       "url": r["url"], "title": r["title"]})

    return {
        "client": tpl["client"],
        "template": tpl["template_name"],
        "keyword": keyword,
        "title": chosen,
        "title_candidates": cands,
        "blocks": blocks,
        "image_slots": slots,
        "fixed_tail_note": "이후 고정 꼬리는 템플릿에 이미 있으므로 건드리지 않는다",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--related", help="related.py pick --json 결과")
    ap.add_argument("--title", help="제목을 직접 지정 (없으면 후보 1번)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    doc = load(args.doc)
    tpl = load(args.template)
    related = load(args.related) if args.related and os.path.exists(args.related) else []

    plan = build(doc, tpl, args.keyword, related, args.title)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print("제목: %s" % plan["title"])
    print("컴포넌트 %d개 / 이미지 슬롯 %d개 / 관련 글 %d개"
          % (len(plan["blocks"]), len(plan["image_slots"]), len(related)))
    for b in plan["blocks"]:
        extra = ""
        if b["component"] == "text" and b.get("paras"):
            extra = "문단 %d" % len(b["paras"])
        elif b["component"] == "table":
            extra = "%dx%d" % (len(b["rows"][0]), len(b["rows"]))
        elif b["component"] == "image":
            extra = b["slot"]
        elif b["component"] in ("quotation", "oglink"):
            extra = (b.get("text") or b.get("title", ""))[:44]
        print("  %-14s %-16s %s" % (b["component"], b["role"], extra))
    print("저장: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
