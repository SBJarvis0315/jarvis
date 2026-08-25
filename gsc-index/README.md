# 노션 플래너 → Search Console 색인 요청 (A안: 클라우드 브라우저)

매일 정해진 시각에 8개 고객사 노션 피드백 플래너를 훑어, URL 이 있고 `색인 요청` 이
`대기` 인 행을 Search Console 에 색인 요청하고 결과를 노션에 되돌려 씁니다.

기존 Aside 루틴과 **동작이 같습니다.** 실제 브라우저로 Search Console 화면을 열고
`색인 생성 요청` 버튼을 누릅니다. 다른 점은 그 브라우저가 사용자 PC 가 아니라
클라우드에서 돈다는 것뿐입니다. **PC 를 켜둘 필요가 없습니다.**

## 현재 상태

- [x] 클라우드에서 헤드리스 크로미움 구동
- [x] 네트워크 정책으로 Google 도메인 허용
- [x] Search Console 접속 (200 확인)
- [ ] **Google 로그인 세션 이관** ← 지금 여기
- [ ] GSC 색인 요청 자동화
- [ ] 노션 기록 (댓글 + 스크린샷 + 상태값)
- [ ] 매일 정시 루틴 등록

## 이 환경에서 브라우저를 띄울 때의 함정 셋

컨테이너는 매 실행마다 새로 뜹니다. 아래를 모르면 매번 같은 자리에서 막힙니다.

| 증상 | 원인 | 해결 |
|---|---|---|
| `playwright install 을 실행하세요` 하고 죽음 | pip 로 받은 playwright 가 기대하는 리비전과 이미지의 크로미움이 다름 | `executable_path` 로 `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` 명시 |
| `ERR_CERT_AUTHORITY_INVALID` | 크로미움 NSS 스토어에 프록시 CA 가 없음 | `scripts/setup-container.sh` 로 `/root/.ccr/ca-bundle.crt` 등록 |
| Google 만 `ERR_CONNECTION_RESET` (curl 은 되는데 브라우저만 안 됨) | 이그레스 게이트웨이가 Google 은 가로채지 않고 통과시키는데, 크로미움이 TLS 1.3 으로 붙으면 핸드셰이크가 리셋됨 | `--ssl-version-max=tls1.2` |

셋 다 `src/gscindex/browser.py` 에 들어 있습니다. **직접 `launch()` 를 부르지 말고
`browser_context()` 를 쓰세요.**

> TLS 1.2 고정은 게이트웨이 제약을 피하기 위한 것입니다. 인증서 검증은 그대로 켜져
> 있습니다. 게이트웨이가 TLS 1.3 통과를 지원하게 되면 이 플래그는 빼도 됩니다.

## 환경 설정

**네트워크 접근** — `Custom` 으로 두고 허용 도메인에 아래가 들어 있어야 합니다.

```
search.google.com
accounts.google.com
*.google.com
*.googleusercontent.com
*.gstatic.com
```

**Setup script** — `gsc-index/scripts/setup-container.sh` 를 걸어둡니다.
certutil 설치, CA 등록, playwright 설치를 매 세션 시작 시 해줍니다.

**환경변수**

| 이름 | 용도 |
|---|---|
| `NOTION_TOKEN` | 노션 (이미 설정됨) |
| `GOOGLE_SESSION_B64` | Google 로그인 세션. 아래 절차로 만듭니다 |

## Google 세션 넣기

색인 요청은 화면의 버튼이라 서비스 계정으로 우회할 수 없습니다. 사람 계정 세션이
살아 있어야 합니다. 그래서 PC 에서 한 번 로그인한 세션을 떠서 클라우드로 옮깁니다.

**PC 에서:**

```bash
pip install playwright
python gsc-index/tools/capture_session.py
```

브라우저가 열리면 `growth@lead-gen.team` 으로 로그인하고 Enter. `google-session.b64`
가 만들어집니다. 그 내용을 환경변수 `GOOGLE_SESSION_B64` 에 넣으세요.

**클라우드에서 확인:**

```bash
cd gsc-index && PYTHONPATH=src python3 tools/verify_session.py
```

`로그인 유지됨` 이 나오면 성공입니다. 아무것도 바꾸지 않고 확인만 합니다.

### 세션은 언제 죽나

데이터센터 IP 에서 붙기 때문에 구글이 재인증을 요구할 수 있습니다. 2단계 인증이
걸려 있으면 더 자주입니다. 쿠키 자체도 만료됩니다.

**완전 무인이 아니라 "대체로 무인 + 가끔 재로그인"입니다.** 세션이 죽으면 루틴이
알려주도록 만들 예정이고, 그때 PC 에서 `capture_session.py` 를 다시 돌리면 됩니다.

이 재로그인 부담이 부담스러우면 색인 요청만 Indexing API 로 바꾸는 선택지가 있습니다
(로그인이 아예 사라짐). 화면 스크린샷 대신 API 응답이 남는 차이가 있습니다.

## 보안

`GOOGLE_SESSION_B64` 는 `growth@lead-gen.team` 계정 **전체**에 대한 열쇠입니다.
Search Console 뿐 아니라 Gmail·드라이브까지 열립니다. 비밀번호와 같은 급으로
다루세요. 저장소 커밋 금지(`.gitignore` 에 이미 넣어두었습니다), 메신저 전달 금지,
환경변수로만 주입, 자동화를 그만두면 그 계정에서 "모든 기기에서 로그아웃".

## 대상 행 판별 규칙

두 조건을 만족하는 행만 처리합니다.

- `URL` 이 채워져 있을 것
- `색인 요청` 이 `대기` 일 것

여기에 **타 플랫폼 발행 건은 제외**합니다. 판별은 `유형` 속성과 URL 도메인을 함께
봅니다.

- `유형` 이 `네이버` 또는 `네이버(UGC)` → 제외
- URL 이 네이버·카카오·티스토리 계열 도메인 → 제외

> 원래 지시서는 `게시판` 속성으로 판별하라고 되어 있었지만, 실제 8개 DB 를 확인한
> 결과 `게시판` 에 값이 들어 있는 곳은 클리어톤의원 한 곳뿐이었습니다(3곳은 속성
> 자체가 없고, 4곳은 옵션이 비어 있음). 네이버 구분은 `유형` 에 들어 있습니다.

탭(뷰) 구분 없이 데이터소스 전체를 훑습니다. `진행중`+`완료` 두 뷰의 합집합이
전체 행이 아니기 때문입니다 — `발행 오류` 상태 행은 두 뷰 어디에도 안 잡히고,
참포도나무병원 `진행중` 뷰에는 `작업년월 = 2026.8` 필터가 따로 걸려 있습니다.
전체를 훑는 쪽이 누락이 없습니다.

## 고객사 데이터소스

| 고객사 | 데이터소스 |
|---|---|
| 클리어톤의원 | `collection://5ec68fa2-06ff-8312-ad80-878accfa81b4` |
| 참포도나무병원 | `collection://37568fa2-06ff-812b-a99c-000b2831bb7b` |
| 클리어서울안과 | `collection://37d68fa2-06ff-81ef-b7ed-000bf520e760` |
| 큐라엘 | `collection://37a68fa2-06ff-81aa-a4f1-000bfa673325` |
| 쉬즈메디병원 | `collection://88c68fa2-06ff-8373-917d-8784bc0bfb4d` |
| 비컴성형외과 | `collection://64f68fa2-06ff-83c0-a269-87a97af4722c` |
| 지혜로운 필라테스 | `collection://88d68fa2-06ff-829f-a7ca-0754351e8f00` |
| 제로클리닉 | `collection://33968fa2-06ff-83c9-9264-0735823732c7` |

`색인 요청` 셀렉트는 8곳 모두 `대기 / 완료 / 오류 / 개수 제한` 4개 옵션을 이미
갖고 있습니다. 새로 만들 필요 없습니다.
