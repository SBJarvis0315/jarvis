# 월간 리포트 자동화

고객사 월간 리포트(AEO/GEO/SEO)를 노션 템플릿 위에 채웁니다. 절차는
`.claude/skills/monthly-report/SKILL.md` 에 있고, 여기 코드는 **사람이 손으로 하던
브라우저 조작과 CSV 집계**만 맡습니다. 소하·서치콘솔 API 는 쓰지 않습니다.

## 역할 나누기

- **노션 쪽 일**(페이지 찾기·표 채우기·필터 바꾸기·콜아웃 지우기)은 에이전트가
  노션 커넥터로 합니다. 이 패키지는 노션을 건드리지 않습니다.
- **소하 쪽 일**(로그인·CSV 내려받기·대시보드 캡쳐)과 **CSV 집계**는 이 패키지가
  합니다. 결과를 작업 디렉터리에 남기면 에이전트가 그걸 읽어 노션에 옮깁니다.

이렇게 나눈 이유: 노션 공개 API 는 뷰 필터를 다루지 못하고, 저장소의 노션 토큰은
리포트 DB 에 접근 권한이 없습니다. 반대로 브라우저 조작과 수천 행 CSV 집계는
에이전트가 직접 하기에 부정확합니다.

## 쓰기

```bash
cd monthly-report
pip install -q playwright        # 브라우저는 환경의 Chromium 을 씁니다

# 대상 달 계산 (직전 달)
PYTHONPATH=src python3 -m monthlyreport --client 참포도나무병원 period

# 소하 화면 정찰 — 수집도 발행도 하지 않습니다
PYTHONPATH=src python3 -m monthlyreport inspect --slug champodonamu --out inspect/champodonamu

# 수집 (프로파일이 채워진 뒤에 돕니다)
PYTHONPATH=src python3 -m monthlyreport --client 참포도나무병원 --month 2026-09 \
  collect --out work/champodonamu-2026-09
```

## 기간 규칙

직전 달의 작업 성과를 그 달 **말일 기준** 데이터로 보고합니다.

| 루틴이 도는 날 | 대상 | 데이터 기준일 | 플래너 작업년월 | 리포트명 |
|---|---|---|---|---|
| 2026-10-01 | 2026년 9월 | 2026-09-30 | `2026.9` | `26.09 … 리포트` |
| 2027-01-01 | 2026년 12월 | 2026-12-31 | `2026.12` | `26.12 … 리포트` |

`--month 2026-08` 이나 `--run-on 2026-10-01` 로 가장할 수 있습니다 (시험용).

## 소하 계정

비밀값은 파일에 두지 않고 환경변수에서만 읽습니다.

```
SOHA_USER_CHAMPODONAMU=mk.champodonamu@gmail.com
SOHA_PASSWORD_CHAMPODONAMU=…
```

약칭은 대문자로 바꾸고 영숫자가 아닌 글자를 `_` 로 바꾼 것입니다. 환경변수가 없으면
`--soha-user` / `--soha-password` 로 넘길 수 있습니다 (리포트 템플릿의 'AEO/GEO
트래킹 대시보드' 콜아웃에 고객사별로 적혀 있습니다).

## 지금 상태

- `period` — 됩니다. 시험 있음.
- `inspect` — 코드는 됩니다. 소하에 닿는 세션에서 한 번 돌려야 합니다.
- `collect` — **아직입니다.** `profiles/soha.json` 이 비어 있어 거부합니다.
  정찰 결과를 보고 채워야 합니다. 선택자를 추측해서 넣지 않습니다.
- CSV 집계(`metrics.json`) — **아직입니다.** 소하 CSV 의 실제 열 이름을 본 뒤에
  씁니다.

### 이그레스

`soha-ai.com` 은 환경의 네트워크 정책에 들어가 있어야 합니다. 정책은 세션이 시작될
때 굳으므로, 도메인을 방금 추가했다면 **새 세션**에서 돌려야 반영됩니다.
프록시 뒤에서는 Chromium 이 TLS 1.3 핸드셰이크로 끊기므로 `--ssl-version-max=tls1.2`
를 붙입니다 (`soha.chromium_args`). 게시판 발행에서 겪은 것과 같은 문제입니다.
