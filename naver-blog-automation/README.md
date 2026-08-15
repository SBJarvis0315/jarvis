# 네이버 브랜드블로그 원고 자동화

노션 콘텐츠 플래너를 읽어, 조건에 맞는 행마다 네이버 블로그 원고를 생성하고
해당 행 페이지 본문에 삽입한 뒤 진행 상황을 바꿉니다.

```
플래너 조회 → 대상 행 추출 → 종류별 지침으로 원고 생성 → 자동 검증 → 삽입 + 상태 변경
```

## 대상 행 조건

아래를 **모두** 만족하는 행만 처리합니다. 판정은 `notionctl.py list` 가 합니다.

- `담당자` 에 **이선우** 태그
- `키워드` 속성에 텍스트 있음
- `진행 상황` = **작성 전**
- `종류` 에 해당하는 지침이 `config.json` 에 등록되어 있음
- 제목에 `템플릿` 이 들어가지 않음

처리에 성공한 행만 `진행 상황` 을 **원고 저장 완료** 로 바꿉니다. 실패한 행은 손대지 않습니다.

## 노션 접근 방식

Claude의 Notion 커넥터는 **승인한 워크스페이스 하나만** 봅니다. 이 플래너는 그 밖에 있어
커넥터로는 열리지 않습니다. 그래서 노션 **내부 통합(Internal Integration) 토큰**으로
REST API를 직접 호출합니다.

### 최초 설정 (한 번만)

1. 플래너가 있는 노션 계정으로 `notion.so/my-integrations` 접속
2. **새 API 통합** 생성 — 이름 `네이버원고자동화`, 워크스페이스는 해당 플래너 쪽, 유형은 **내부**
3. 발급된 `ntn_...` 시크릿 복사
4. 노션에서 플래너 페이지 `⋯` → **연결** → 위 통합 추가 (이걸 해야 API에 보입니다)
5. claude.ai/code 환경 설정
   - 환경변수 `NOTION_TOKEN_NAVER` = 3번 값
     (`NOTION_TOKEN` 은 다른 자동화가 쓰는 값입니다. 덮어쓰지 마세요.)
   - 허용 도메인에 `api.notion.com` 추가
6. **새 세션**에서 실행 (환경변수는 세션 시작 시 한 번만 읽힙니다)

토큰은 문서·커밋·채팅 어디에도 남기지 않습니다.

## 사용법

```bash
# 연결과 권한 확인
python3 naver-blog-automation/notionctl.py check

# 접근 가능한 DB 찾기 → config.json 의 planner_db_id 채우기
python3 naver-blog-automation/notionctl.py find-planner

# 속성 이름·선택지 확인 → config.json 의 properties 대조
python3 naver-blog-automation/notionctl.py schema <db_id>

# 작업 대상 추출 (--verbose 로 제외 사유까지)
python3 naver-blog-automation/notionctl.py list --client 클리어서울안과 --json work.json --verbose

# 원고 검증
python3 naver-blog-automation/tools/check.py <초안> --mode info --emit <최종>
python3 naver-blog-automation/tools/check.py <초안> --mode paper --keyword "라식수술후관리" --emit <최종>

# 삽입 + 상태 변경
python3 naver-blog-automation/notionctl.py write --client 클리어서울안과 \
    --page <page_id> --body <최종> --divider --status "원고 저장 완료"
```

## 원고 마커

원고는 마커가 붙은 평문으로 쓰고, `notionctl.py write` 가 노션 블록으로 변환합니다.

| 마커 | 변환 결과 |
|---|---|
| `[표]` ~ `[/표]` | 표 블록. 줄 안의 `\|` 가 열 구분. 첫 셀이 `구분`·`항목`·`단계` 면 헤더행 지정 |
| `[인용구]` ~ `[/인용구]` | 인용 블록 |
| `**문장**` | 볼드 |
| `[이미지]` | 변환하지 않고 텍스트 그대로 (삽입 위치 표시) |
| `<<파트명>>` ~ `<</파트명>>` | 글자수 검증용 경계. 최종 원고에서는 제거됨 |

## 자동 검증

`tools/check.py` 가 지침 위반을 잡습니다. 통과하지 못한 원고는 노션에 쓰지 않습니다.

**공통** — 금지 서술어(흔들린다·갈린다·판가름 난다 등), 의료광고 위험 표현(최고·완치·100%·부작용 없음 등), 본문 이모지, 단어 15회 초과 반복

**정보성글 (`--mode info`)** — 파트별 글자수(결론 선제시 200 / 서론 300 / 소제목 1~3 각 400 / 소제목 4 150 / 마무리 350), 표 9개 이상, 인용구 6개 이상, 전체 3000자 이상

**논문글 (`--mode paper`)** — 파트별 글자수(서론 300 / 소제목 1~3 각 450 / 마무리 150 / 총 1600), 소제목 정확히 3개, 논문 인용 블록 3개 이상, 링크 3개 이상, 본문 키워드 정확히 5회

## 디렉터리

```
config.json                     고객사·플래너·속성명·지침 매핑
notionctl.py                    노션 REST 클라이언트 (check/find-planner/schema/list/write)
routine-prompt.md               Claude 루틴에 붙여넣을 지침 전문
tools/check.py                  지침 준수 자동 검증기
clients/<고객사>/guideline-정보성글.md
clients/<고객사>/guideline-논문글.md
clients/<고객사>/reference.txt   병원·원장 정보, 말투, 시술 목록, FAQ
clients/<고객사>/samples/        톤앤매너 참고용 기존 발행글
drafts/                         생성된 원고
drafts/samples/                 검증 통과 참고본
```

## 새 고객사 추가

1. `clients/<슬러그>/` 에 `guideline-<종류>.md`, `reference.txt`, `samples/` 를 넣습니다
2. `config.json` 의 `clients` 배열에 항목 하나를 추가합니다
3. 그 고객사 플래너에도 노션 통합을 연결합니다 (페이지 `⋯` → 연결)

지침은 파일만 고치면 다음 실행부터 반영됩니다. 배포 절차가 따로 없습니다.

## 현재 상태

| 항목 | 상태 |
|---|---|
| 정보성글 지침 | 확보 |
| 논문글 지침 | 확보 (보완 제안 포함, 검토 필요) |
| 검증기 | 두 모드 동작 확인 |
| 마커 → 노션 블록 변환 | 표 9개·인용구 6개·볼드 12개 변환 확인 |
| `config.json` 의 `planner_db_id` | **미확인** — 토큰 연결 후 `find-planner` 로 채워야 함 |
| 속성명 (`콘텐츠 번호`·`종류` 등) | 스크린샷 기준으로 채워둠. `schema` 로 대조 필요 |
