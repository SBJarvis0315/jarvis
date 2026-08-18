# 네이버 블로그 발행 자동화

사람이 손으로 뽑은 DOCX 원고를 읽어, 고객사 템플릿 순서대로 배치하고
이미지를 채운 뒤 네이버 블로그에 발행합니다.

```
DOCX → 파싱 → 템플릿 배치 → 이미지 채움 → 관련 글 링크 → 스마트에디터 발행
```

## 파이프라인

```bash
cd naver-blog-automation

# 1. 원고 읽기
python3 publish/docxparse.py 원고.docx --out work/ --heading-lines 1

# 2. 관련 글 후보 (최초 1회 인덱싱 후 재사용)
python3 publish/related.py index --blog aoske551 --cache work/aoske551.json
python3 publish/related.py pick  --cache work/aoske551.json \
    --keyword 3차신경통 --count 2 --json work/related.json

# 3. 템플릿 배치
python3 publish/plan.py --doc work/doc.json \
    --template clients/ducheong/template.json \
    --keyword 3차신경통 --related work/related.json --out work/plan.json

# 4. 이미지 (사진이 있는 PC에서)
python3 publish/images.py catalog --dir "C:/.../사진" --out work/catalog.json
python3 publish/images.py todo    --catalog work/catalog.json
python3 publish/images.py caption --catalog work/catalog.json --file "연출/x.jpg" --text "…"
python3 publish/images.py assign  --plan work/plan.json --catalog work/catalog.json --out work/assign.json
python3 publish/images.py stock   --assign work/assign.json --out work/media/

# 5. 발행 — 미구현. 셀렉터 실측 후 추가
```

## 원고 작성 규칙

DOCX를 뽑을 때 아래만 지키면 파서가 정확히 읽습니다.

| 항목 | 규칙 |
|---|---|
| 제목 후보 | `[제목 후보]` 줄 뒤에 `1.` `2.` `3.` 으로 나열 |
| 소제목 | `1. ` 넘버링, **한 줄**로 (두청한의원 기준) |
| 마무리 | 마무리 직전에 하이픈 한 줄 `-` |
| 표 | 워드 표 그대로. 도입 문장 바로 뒤에 둔다 |
| 강조 | 워드 볼드 서식 그대로 |

마무리 하이픈이 없으면 종결 어투로 추정하는데, 두 문단쯤 늦게 잡히는 경우가 있습니다.

## 이미지

내부 사진을 먼저 쓰고 남는 자리만 무료 라이선스 스톡에서 받습니다.

파일명만으로는 무엇이 찍혔는지 알 수 없어, 사진마다 한 줄 설명을 붙여 카탈로그를
만들어 둡니다. 이 설명이 슬롯 문맥과 맞춰지는 기준입니다. 한 번 붙여두면
다음 원고부터는 그대로 재사용됩니다.

- 한 글 안에서 같은 사진을 두 번 쓰지 않습니다
- 인사말 직후 자리는 본문 문맥이 아니라 원장 인물·진료실 전경을 우선합니다
- 표 바로 앞에는 이미지를 넣지 않습니다 (도입 문장과 표가 떨어지므로)
- 스톡 이미지는 출처 URL·라이선스·저작자를 `media/manifest.json` 에 남깁니다

## 고객사

### 두청한의원 (`clients/ducheong/`)

`template.json` 은 발행글 2건을 직접 열어 컴포넌트 순서를 대조한 것입니다.

- 블로그 `blog.naver.com/niceolive/` — 다른 고객사 글도 올라오므로 `reference_posts` 2건만 기준
- 관련 글 링크는 `blog.naver.com/aoske551/` 에서만 (755건 인덱싱)
- 소제목 3개 구조, 이미지 5~6장, 형광펜 `#fff8b2`
- 예약·카톡·지도 등 고정 꼬리는 `fixed_tail` 로 분리해 건드리지 않습니다

## 실행 환경

| 단계 | 어디서 |
|---|---|
| 1~3 (파싱·배치·링크) | 아무 데서나 |
| 4 (이미지) | **사진이 있는 PC** |
| 5 (발행) | **사용자 PC** — 네이버가 데이터센터 IP 로그인을 막습니다 |

이 클라우드 환경에서 4~5를 돌리려면 허용 도메인에 아래가 필요합니다.
`api.openverse.org`, `api.pexels.com`, `pixabay.com`

## 노션 플래너 연동 (보류)

원고를 노션에서 자동 생성하던 경로입니다. 플래너가 있는 워크스페이스에
통합을 만들 권한이 없어 멈춰 있습니다. 관련 파일은 그대로 두었습니다.

`notionctl.py`, `config.json`, `routine-prompt.md`, `tools/check.py`,
`clients/clearseoul-eye/`

## 디렉터리

```
publish/docxparse.py   DOCX → doc.json
publish/plan.py        doc.json + template.json → plan.json
publish/images.py      카탈로그·배정·스톡 수집
publish/related.py     관련 글 인덱싱·선정
clients/<고객사>/template.json
clients/<고객사>/guideline-*.md
```
