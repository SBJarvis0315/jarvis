# 세명종합병원 GEO·AEO·SEO 제안서 (웹 버전)

기존 PPT 제안서(P-2026-0805)를 한 장짜리 인터랙티브 웹 페이지로 다시 만든 것입니다.
`index.html` 하나를 브라우저로 열면 바로 보입니다. 서버나 빌드 과정은 필요 없습니다.

## 구성

```
proposals/semyung-geo/
├── index.html                 본문 · 스타일 · 스크립트 전부
├── assets/
│   ├── logo-h-dark.png        리드젠랩 로고 (밝은 배경용)
│   ├── logo-h-white.png       리드젠랩 로고 (어두운 배경용)
│   ├── clients/*.png          고객사 로고 32개 (원본 PPT에서 추출, 배경 여백 제거)
│   ├── fonts/PretendardVariable.woff2   Pretendard 가변 폰트 (KS X 1001 한글 + 라틴 서브셋)
│   └── vendor/gsap.min.js, ScrollTrigger.min.js   모션 라이브러리
└── README.md
```

## 발송 전 반드시 확인할 것

`index.html` 맨 위 주석에도 같은 내용이 있습니다.

1. **작업 전후 노출률 5개 사례** 수치는 원본 PPT에 "제안용 가안"으로 적혀 있던 값입니다.
   실제 운영 데이터로 바꾼 뒤 발송하세요. `index.html` 안 스크립트의 `CASES` 배열을 고치면 카드와 막대가 함께 바뀝니다.
2. **도입부 AI 답변 시뮬레이션**의 2·3순위 병원 순서는 SoV 예비 스캔 명단을 바탕으로 재구성한 예시입니다.
   실제 답변 캡처와 맞춰 주세요. 스크립트의 `SIM` 배열입니다.
3. **제안일과 진단 기준일**은 2026.08.05로 통일돼 있습니다. 발송일에 맞춰 바꾸세요.
   (히어로 상단, 요약 각주, 진단 각주, 내비 우측 `P-2026-0805`)
4. 가격 · 발행량 · KPI 범위는 원본 PPT 값을 그대로 옮겼습니다.

## 다른 병원 제안서로 재활용할 때

- 본문 텍스트는 전부 `index.html`의 HTML 안에 있습니다. 섹션 순서대로 바꾸면 됩니다.
- 데이터 블록은 스크립트 상단에 모여 있습니다.
  - `SOV` : 답변 점유율 막대 차트
  - `SIM` : 도입부 검색 시뮬레이션 (질의 → 인용 병원 → 판정)
  - `CASES` : 작업 전후 사례 카드
- 숫자 카운트업은 `data-count`, 막대 길이는 `data-w`(%) 속성으로 조절합니다.

## 쓰인 오픈소스

| 항목 | 라이선스 | 용도 |
|---|---|---|
| [Pretendard](https://github.com/orioncactus/pretendard) 1.3.9 | SIL OFL 1.1 | 본문 · 제목 서체 |
| [IBM Plex Mono](https://fonts.google.com/specimen/IBM+Plex+Mono) | SIL OFL 1.1 | 질의 문자열 · 라벨 (Google Fonts에서 로드, 오프라인이면 시스템 고정폭으로 대체) |
| [GSAP](https://gsap.com) 3.13.0 + ScrollTrigger | GSAP Standard "no charge" license (2025년부터 상업용 포함 무료) | 스크롤 등장 · 카운트업 · 막대 · 타이핑 모션 |
| [im-not-ai](https://github.com/epoko77-ai/im-not-ai) humanize-korean 규칙 | 참고 | 문장 윤문 기준 (번역투 · 대구 반복 · 결산 관용구 제거 등) |

JS가 꺼져 있거나 `prefers-reduced-motion`이 켜진 환경에서도 모든 수치와 막대는 최종 상태로 보입니다.
