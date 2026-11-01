# 세명종합병원 GEO·AEO·SEO 제안서 (웹 버전)

기존 PPT 제안서(P-2026-0805)를 한 장짜리 인터랙티브 웹 페이지로 다시 만든 것입니다.
`index.html` 하나를 브라우저로 열면 바로 보입니다. 서버나 빌드 과정은 필요 없고, 폰트와 스크립트가 모두 로컬에 있어 인터넷 없이도 똑같이 보입니다.

## 구성

```
proposals/semyung-geo/
├── index.html                 본문 · 스타일 · 스크립트 전부
├── assets/
│   ├── logo-h-dark.png        리드젠랩 로고 (밝은 배경용)
│   ├── logo-h-white.png       리드젠랩 로고 (어두운 배경용)
│   ├── clients/*.png          고객사 로고 32개 (원본 PPT에서 추출, 배경 여백 제거)
│   ├── fonts/
│   │   ├── HahmletVariable.woff2      제목용 세리프 (KS X 1001 한글 + 라틴 서브셋)
│   │   ├── WantedSansVariable.woff2   본문용 산세리프 (같은 범위 서브셋)
│   │   └── OFL-*.txt                  폰트 라이선스
│   └── vendor/
│       ├── gsap.min.js, ScrollTrigger.min.js, SplitText.min.js   모션
│       └── lenis.min.js                                           스무스 스크롤
└── README.md
```

## 발송 전 반드시 확인할 것

`index.html` 맨 위 주석에도 같은 내용이 있습니다.

1. **작업 전후 노출률 5개 사례** 수치는 원본 PPT에 "제안용 가안"으로 적혀 있던 값입니다.
   실제 운영 데이터로 바꾼 뒤 발송하세요. 스크립트의 `CASES` 배열을 고치면 카드와 막대가 함께 바뀝니다.
2. **도입부 AI 답변 시뮬레이션**의 2, 3순위 병원 순서는 예비 스캔 명단을 바탕으로 재구성한 예시입니다.
   실제 답변 캡처와 맞춰 주세요. 스크립트의 `SIM` 배열입니다.
3. **제안일과 진단 기준일**은 2026.08.05로 통일돼 있습니다. 발송일에 맞춰 바꾸세요.
   (히어로 상단, 요약 각주, 진단 각주, 메뉴 하단과 푸터의 `P-2026-0805`)
4. 가격, 발행량, KPI 범위는 원본 PPT 값을 그대로 옮겼습니다.

## 다른 병원 제안서로 재활용할 때

- 본문 텍스트는 전부 `index.html`의 HTML 안에 있습니다. 섹션 순서대로 바꾸면 됩니다.
- 데이터 블록은 스크립트 상단에 모여 있습니다.
  - `SOV` : 답변 점유율 막대
  - `SIM` : 도입부 검색 시뮬레이션 (질문 → 인용 병원 → 판정)
  - `CASES` : 작업 전후 사례
  - `QUERIES` : 도입부 아래로 흐르는 질의 띠
- 숫자 카운트업은 `data-count`, 막대 길이는 `data-w`(%) 속성으로 조절합니다.
- 한글은 KS X 1001 완성형 2,350자 범위로 서브셋했습니다. 그 밖의 글자(예: 옛한글, 드문 음절)를 쓰면 그 글자만 시스템 폰트로 표시됩니다.

## 동작

- 스크롤: Lenis 스무스 스크롤, 섹션 제목은 줄 단위로 올라오며 나타남 (GSAP SplitText)
- 도입부: 질문 타이핑 → 인용 병원 순서대로 등장 → 판정. 3개 질문이 9초마다 바뀌고, 마우스를 올리면 멈춤
- 로드맵: 데스크톱에서는 화면을 고정한 채 가로로 넘어가고, 모바일에서는 손가락으로 옆으로 넘김
- 실행 계획: 아코디언. 첫 항목만 펼쳐진 상태로 시작
- 상단 `목차` 버튼: 전체 화면 메뉴
- 데스크톱에서 커스텀 커서와 자석 버튼, 전체에 얇은 그레인
- `prefers-reduced-motion`이 켜져 있거나 JS가 꺼져 있으면 모션 없이 최종 상태로 표시

## 쓰인 오픈소스

| 항목 | 라이선스 | 용도 |
|---|---|---|
| [Hahmlet](https://github.com/google/fonts/tree/main/ofl/hahmlet) | SIL OFL 1.1 | 제목 · 큰 숫자 (세리프) |
| [Wanted Sans](https://github.com/wanteddev/wanted-sans) | SIL OFL 1.1 | 본문 |
| [JetBrains Mono](https://fonts.google.com/specimen/JetBrains+Mono) | SIL OFL 1.1 | 작은 라벨 (Google Fonts에서 로드, 오프라인이면 시스템 고정폭으로 대체) |
| [GSAP](https://gsap.com) 3.13.0 + ScrollTrigger + SplitText | GSAP Standard "no charge" license (2025년부터 상업용 포함 무료) | 리빌 · 카운트업 · 핀 스크롤 · 타이핑 |
| [Lenis](https://github.com/darkroomengineering/lenis) 1.3.27 | MIT | 스무스 스크롤 |
| [im-not-ai](https://github.com/epoko77-ai/im-not-ai) humanize-korean 규칙 | 참고 | 문장 윤문 기준 |
