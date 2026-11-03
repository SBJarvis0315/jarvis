# Claude SEO 플러그인 사용 가이드

Nov 3, 2026

## 1. 이게 무엇인가

[Claude SEO](https://github.com/AgriciDaniel/claude-seo)는 클로드 코드 안에서 돌아가는 무료 오픈소스(MIT) SEO 감사 도구입니다. 사이트 주소 하나를 주면 10~15분 안에 기술 SEO, 콘텐츠 품질(E-E-A-T), 스키마(구조화 데이터), 속도(Core Web Vitals), AI 검색 노출(GEO), 로컬 SEO 등을 한꺼번에 점검하고, 중요한 순서대로 정리한 실행 계획을 마크다운 보고서로 줍니다. 전문 에이전트 19개와 하위 스킬 26개로 이루어져 있고, 전체 감사 때는 최대 17개 에이전트가 동시에 움직입니다.

우리 팀 기준으로는 고객사 워드프레스 블로그나 자체 게시판 사이트를 **발행 전후로 점검**하고, 신규 고객사 **온보딩 때 현황을 빠르게 파악**하는 용도로 쓰기 좋습니다.

## 2. 설치 상태

이 저장소에는 이미 설치되어 있습니다. `.claude/settings.json`에 마켓플레이스와 플러그인이 등록되어 있어서, jarvis 저장소를 여는 클로드 코드 세션(클라우드 세션 포함)은 플러그인을 자동으로 읽어 들입니다.

| 파일 | 역할 |
| --- | --- |
| `.claude/settings.json` | `extraKnownMarketplaces`에 `AgriciDaniel/claude-seo` 마켓플레이스, `enabledPlugins`에 `claude-seo@agricidaniel-claude-seo`를 등록 |

로컬 PC의 클로드 코드에서 jarvis 폴더를 열면 "프로젝트 플러그인을 설치할까요?" 하고 한 번 물어봅니다. 허용하면 끝입니다. jarvis 폴더 밖에서도 쓰고 싶으면(사용자 범위 설치) 클로드 코드 안에서 아래 세 줄을 치면 됩니다.

```
/plugin marketplace add AgriciDaniel/claude-seo
/plugin install claude-seo@agricidaniel-claude-seo
/seo setup
```

요구 사항: 클로드 코드 1.0.33 이상, 파이썬 3.11~3.14.

## 3. 처음 한 번 할 일

```
/seo setup
```

플러그인 전용 파이썬 가상환경과 헤드리스 크로미움(화면 없는 브라우저)을 만듭니다. 시스템의 다른 파이썬 패키지는 건드리지 않습니다. 몇 분 걸립니다. 이후 상태 확인은 아래로 합니다.

```
/seo doctor
```

"ready: true"가 나오면 준비 끝입니다. 로컬 PC에서는 한 번만 하면 됩니다.

### 클라우드 세션에서는 감사가 돌아가지 않는다

이 플러그인은 **로컬 PC의 클로드 코드에서** 쓰는 것을 전제로 합니다. 클라우드 세션(지금 루틴이 도는 환경)에서 설치와 `/seo setup`까지는 되지만(2026-11-03 확인), 실제 사이트 점검은 두 가지 이유로 막힙니다.

1. 클라우드 컨테이너는 바깥 인터넷을 로컬 프록시(127.0.0.1)로만 나가는데, 플러그인의 페이지 수집기는 보안(SSRF 방지)을 위해 사설 주소 프록시를 거부합니다. 이 검사는 끌 수 없습니다.
2. 환경의 네트워크 정책이 허용 목록 방식이라 고객사 도메인과 크로미움 다운로드 서버(`cdn.playwright.dev`)가 차단됩니다. 환경 설정(세션 제목줄의 클라우드 환경 메뉴 → Edit → Network access)에서 허용 도메인을 넓힐 수는 있지만, 1번 때문에 그래도 수집기는 동작하지 않습니다.

따라서 **SEO 감사는 팀원 PC의 클로드 코드에서 jarvis 폴더를 열고 실행**하세요. 설치는 2장대로 자동 제안됩니다.

## 4. 기본 사용법

모든 명령은 `/seo <명령> <주소>` 꼴입니다. `/seo`만 치면 전체 명령 목록이 나옵니다.

### 가장 많이 쓸 다섯 가지

| 명령 | 하는 일 | 언제 쓰나 |
| --- | --- | --- |
| `/seo audit https://고객사.com` | 사이트 전체 감사. 업종을 자동 판별하고 에이전트를 병렬로 돌려 0~100점 건강 점수와 우선순위 실행 계획을 냄 | 신규 고객사 온보딩, 분기별 점검 |
| `/seo page https://고객사.com/글주소` | 글 한 편을 깊게 분석(제목, 메타, 본문 구조, 스키마, 내부 링크) | 발행 직후 검수, 성과 안 나오는 글 진단 |
| `/seo schema https://고객사.com/글주소` | 스키마 감지·검증, 빠진 스키마(FAQ, Article, LocalBusiness 등) 코드 생성 | Rank Math 스키마 설정 확인 |
| `/seo geo https://고객사.com` | 구글 AI 개요, ChatGPT, Perplexity에 인용될 가능성 점검 | AI 검색 대응 |
| `/seo content-brief 키워드` | 목표 키워드, 개요, 내부 링크까지 담은 콘텐츠 기획안 | 플래너에 키워드 넣기 전 기획 |

### 나머지 명령

**기술 SEO**

| 명령 | 하는 일 |
| --- | --- |
| `/seo technical <url>` | 크롤링·색인·리다이렉트·속도 등 9개 범주 기술 감사 |
| `/seo sitemap <url>` 또는 `/seo sitemap generate` | 사이트맵 분석 또는 생성 |
| `/seo images <url>` | 이미지 최적화(alt, 용량, 형식) 점검 |
| `/seo hreflang <url>` | 다국어 사이트 hreflang 점검·생성 |
| `/seo drift baseline <url>` | 현재 상태를 기준점으로 저장 |
| `/seo drift compare <url>` | 기준점 대비 무엇이 바뀌었는지 비교 |
| `/seo google [명령]` | 서치콘솔, PageSpeed, CrUX, GA4 데이터 연동(API 키 필요, 아래 6장) |

**콘텐츠**

| 명령 | 하는 일 |
| --- | --- |
| `/seo content <url>` | E-E-A-T와 콘텐츠 품질 분석 |
| `/seo cluster 키워드` | 검색 결과 기반 토픽 클러스터링, 콘텐츠 구조 설계 |
| `/seo sxo <url>` | 검색 경험 최적화: 페이지 유형, 사용자 스토리, 페르소나 |
| `/seo competitor-pages <url>` | 경쟁사 비교 페이지 기획 |
| `/seo plan local` | 업종별 전략 수립(saas, local, ecommerce, publisher, agency) |

**로컬·커머스**

| 명령 | 하는 일 |
| --- | --- |
| `/seo local <url>` | 구글 비즈니스 프로필, 인용, 리뷰, 지도 노출 점검(병원·필라테스 같은 오프라인 고객사에 유용) |
| `/seo maps [명령]` | 지도 순위 격자, GBP 감사, 리뷰·경쟁사 분석 |
| `/seo backlinks <url>` | 백링크 프로필 분석(Moz, Bing, Common Crawl 무료 소스) |
| `/seo ecommerce <url>` | 쇼핑몰 SEO, 상품 스키마 |

**AI·에이전트**

| 명령 | 하는 일 |
| --- | --- |
| `/seo agentic <url>` | AI 에이전트 접근성: llms.txt, 접근성 트리, 마크다운 제공 여부 |

## 5. 결과물은 어디에 남나

보고서는 **명령을 실행한 폴더** 아래 `도메인-audit/` 같은 폴더에 마크다운과 JSON으로 저장됩니다. jarvis 저장소에서 돌리면 저장소 루트에 생기는데, 이 폴더는 `.gitignore`에 넣어 두어 커밋되지 않습니다. 보관할 보고서는 노션이나 고객사 폴더로 옮기세요.

감사가 끝난 뒤 "PDF로 만들까요?" 하고 물어보면 허용하면 됩니다. 직접 만들 때는 `/seo google report`입니다.

## 6. 구글 API 연동(선택)

API 키 없이도 다 동작합니다. 다만 Core Web Vitals는 실험실 추정치이고 색인 여부는 페이지에서 유추합니다. 실제 서치콘솔 데이터와 실사용자 속도 데이터를 보려면 아래를 한 번만 하면 됩니다.

```
/seo google setup
```

클로드가 단계별로 안내합니다. 요약하면 구글 클라우드 프로젝트 하나 만들고, Search Console API·PageSpeed Insights API·Chrome UX Report API·GA4 Data API를 켠 뒤, API 키(속도 데이터용)와 서비스 계정 JSON(서치콘솔·GA4용)을 만들어 등록합니다. 서비스 계정 이메일을 각 고객사 서치콘솔 속성에 사용자로 추가해야 데이터가 읽힙니다. 모두 무료 할당량 안에서 돌아갑니다.

키는 이 저장소에 적지 않습니다. 로컬에서는 `~/.config/claude-seo/` 아래에, 클라우드에서는 환경 설정의 환경변수에 넣습니다(저장소의 다른 비밀값과 같은 원칙).

## 7. 우리 팀 추천 흐름

1. **신규 고객사 온보딩**: `/seo audit`으로 전체 감사 → 보고서의 상위 5개 항목을 고객사 제안서에 반영 → `/seo drift baseline`으로 기준점 저장.
2. **키워드 기획**: 플래너에 키워드를 넣기 전 `/seo cluster 키워드`로 묶음을 보고, `/seo content-brief 키워드`로 기획안을 뽑아 원고 지시에 활용.
3. **발행 후 검수**: 09:00·19:00 루틴이 발행한 글 중 중요한 글은 `/seo page <글주소>`로 제목·메타·스키마 확인. 스키마가 비면 `/seo schema`가 만들어 준 JSON-LD를 Rank Math에 붙여 넣기.
4. **월 1회 점검**: `/seo drift compare`로 지난달 대비 변화 확인, 오프라인 고객사는 `/seo local`.

## 8. 비용과 주의사항

- **플랜 사용량**: 전체 감사(`/seo audit`)는 판단이 필요한 에이전트 5개가 Opus로, 나머지는 Sonnet으로 돕니다. 단일 페이지 점검보다 사용량이 큽니다. 고객사 한 곳에 한 번 돌리는 용도로 쓰고, 일상 점검은 `/seo page`나 `/seo schema`로 하세요.
- **데이터**: 분석하는 페이지 내용은 클로드 코드의 다른 작업처럼 Anthropic 모델로 전송됩니다. 그 외 외부 서비스로는 나가지 않습니다(확장 기능을 직접 연결하지 않는 한). 일부 점검은 위키백과, 레딧, Common Crawl 같은 공개 소스를 읽습니다.
- **자바스크립트 사이트**: 본문이 JS로 그려지는 사이트는 자동으로 헤드리스 브라우저로 열어 봅니다. 그래서 `/seo setup`이 필요합니다.
- **한계**: 스크롤이나 클릭 뒤에만 보이는 콘텐츠는 결과가 흔들릴 수 있습니다.
- **클라우드 세션**: 3장에서 적었듯 클라우드 컨테이너에서는 사이트 수집이 막힙니다. 루틴(예약 작업)에 `/seo` 명령을 넣지 마세요.
- **삭제**: 클로드 코드에서 `/plugin uninstall claude-seo@agricidaniel-claude-seo`. 저장소에서 완전히 빼려면 `.claude/settings.json`의 등록 항목도 지웁니다.

## 9. 더 읽을 것

- 명령 전체 목록: [docs/COMMANDS.md](https://github.com/AgriciDaniel/claude-seo/blob/main/docs/COMMANDS.md)
- 감사 방법론: [thinking-framework.md](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo/references/thinking-framework.md)
- 개인정보 처리: [PRIVACY.md](https://github.com/AgriciDaniel/claude-seo/blob/main/PRIVACY.md)
