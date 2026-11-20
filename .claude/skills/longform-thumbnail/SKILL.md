---
name: longform-thumbnail
description: 노션 플래너의 롱폼 행 중 썸네일이 비어 있는 행에, ChatGPT 구독으로 만든 실사 배경 위에 운영자가 고른 네 가지 틀(card·bottomleft·klavuu·ivory)로 제목을 얹은 고급 썸네일을 만들어 붙입니다. 롱폼 썸네일 루틴이 이 스킬을 부르고, 팀원이 /longform-thumbnail 로 직접 실행할 수도 있습니다. "롱폼 썸네일", "고급 썸네일", "실사 썸네일" 요청에 사용하세요.
---

# 롱폼 고도화 썸네일

숏폼 썸네일은 기존 루틴(`wp-thumbnail` 스킬)이 고객사 디자인 파일로 찍어 냅니다.
**이 스킬은 롱폼만** 맡습니다. 배경 사진은 ChatGPT 구독으로 만들고(글자 없이),
글자·로고·효과는 코드 틀이 얹습니다. 작업 디렉터리는 `notion-wp-publish/` 입니다.

## 0. 시작 전 확인 — Codex 설치와 ChatGPT 인증

배경 생성은 `gpt-image` 스킬(Codex CLI + ChatGPT 구독 인증)로만 합니다. 클라우드 루틴은
매번 새 컴퓨터라, 아래 순서로 매 회차 준비합니다(저장소 루트에서).

1. Codex 가 없으면 공식 설치기로 설치합니다.
   ```bash
   command -v codex || node .claude/skills/gpt-image/scripts/gpt_image.mjs install-codex --yes
   ```
2. 로그인 상태를 봅니다: `codex login status`
   - `Logged in using ChatGPT` 또는 `Logged in using personal access token` 이면 3단계는 건너뜁니다.
3. 로그인이 없고 환경변수 `CODEX_ACCESS_TOKEN`(ChatGPT Business 워크스페이스의 Codex
   액세스 토큰)이 있으면 그것으로 로그인합니다. **토큰 값을 화면·로그·커밋에 절대 출력하지 않습니다.**
   ```bash
   printf '%s' "$CODEX_ACCESS_TOKEN" | codex login --with-access-token >/dev/null 2>&1; codex login status
   ```
4. 그래도 위 두 문구가 아니면 **여기서 멈추고** 보고합니다.
   - 토큰이 없으면: "Codex 액세스 토큰이 없어 롱폼 썸네일을 만들지 못했습니다"
   - 토큰 로그인이 실패하면(만료·폐기): "Codex 액세스 토큰이 만료됐거나 무효입니다. 새 토큰으로 교체가 필요합니다"
   - 로그인 코드를 띄우지 않습니다(사람이 없는 시간에 돕니다).
- OpenAI API 키·Images API 로 우회하지 않습니다. `OPENAI_API_KEY` 를 찾거나 쓰지 않습니다.

## 1. 대상 행 뽑기

```bash
PYTHONPATH=src python3 -m notionwp.longform_thumb list
```

- 설정표에서 상태가 '활성'이고 **'썸네일' 칸에 롱폼이 있는 고객사**만 봅니다.
- 그 플래너에서 유형이 롱폼이고, 제목이 있고('템플릿' 글자 없음), 썸네일 칸이 빈 행만 나옵니다.
- `[]` 이면 "롱폼 썸네일 대상 없음" 한 줄로 끝냅니다. 흔하고 정상입니다.
- 한 회차에 **최대 6건**만 처리합니다(구독 사용량 보호). 나머지는 다음 회차로 넘깁니다.

## 1.5 고객사마다: 캔버스와 잘림 확인 (글자 잘림 방지 — 1순위)

틀은 고객사 디자인 파일(`designs/<고객사>.json`)의 `width`·`height` 를 캔버스로 쓰고,
`view_crops` 에 적힌 비율(가로/세로)로 사이트가 가운데를 잘라 보여 준다고 보고
**모든 잘림에서 살아남는 영역 안에만** 글자·로고를 넣습니다. 예) 지혜로운 필라테스는
1200x900 캔버스, `view_crops: [1.3333, 2.0]`(목록 카드 4:3 · 글 상세 커버 2:1).

- 디자인 파일에 `view_crops` 가 **없는** 고객사를 처음 처리할 때는, `wp-thumbnail` 스킬
  「1.5단계」와 같은 방법(테마 style.css 의 `aspect-ratio`·`object-fit`, srcset 크기)으로
  그 사이트가 롱폼 썸네일을 어떤 비율로 잘라 보여 주는지 재고, 디자인 파일에
  `view_crops` 한 줄만 추가해 커밋합니다. 다른 값(색·크기·골격)은 절대 바꾸지 않습니다.
  자르지 않는 사이트면 `view_crops: []` 로 적어 재 봤다는 표시를 남깁니다.
- 사이트가 열리지 않아 알 수 없으면 추측해서 적지 말고 비워 둡니다(캔버스 전체를 씁니다).

## 2. 행마다: 틀 고르기

| 틀 | 어울리는 주제 | 배경 사진 | 글자 |
|---|---|---|---|
| `card` | 부작용·주의사항·회복·통증·피부 고민 | 얼굴 없는 질감 접사(피부결·물방울·원단·액체), 전체가 부드럽게 흐림 | 분류 표시(`--pill`, 2~6자) + 윗줄 + 큰 제목 |
| `bottomleft` | 시술 비교·효과·리프팅·얼굴/바디 라인 | 인물 화보. 얼굴은 오른쪽, 왼쪽 절반은 비운 배경 | 윗줄 + 큰 제목, 왼쪽 아래 |
| `klavuu` | 제품·성분·가격·스킨부스터, 또는 인물 화보 | 브랜드 없는 제품 연출(앰플·튜브, 하늘·버블·새틴·꽃잎) 또는 인물 클로즈업. 오른쪽 위는 비움, 아래쪽은 흰 번짐 | 윗줄 + 큰 제목, 키워드는 `**굵게**` |
| `ivory` | 법률·세무·상담·절차·서류·비용 구조 | 손·서류·만년필 같은 사물 실사. 왼쪽은 따뜻한 빈 공간 | 윗줄 + 큰 제목(두 줄 가능) |

- **디자인 파일에 `longform_style` 이 있으면 그 틀만 씁니다**(운영자 고정). 예) 지혜로운
  필라테스 = `ivory`. 이때 `render` 에 `--style` 을 빼면 자동으로 그 틀이 쓰이고, 다른 틀을
  주면 명령이 거부합니다. 배경 사진도 그 틀의 빈자리 규칙에 맞춰 만듭니다.
- 고정이 없는 고객사는 같은 회차에 같은 틀만 연달아 나오지 않게 섞습니다.
- 법률·세무 고객사는 `ivory` 를 기본으로, 병원은 위 표대로 고릅니다.

## 3. 행마다: 글자 정하기

- **윗줄(line1)**: 독자의 상황이나 질문. 18자 안팎. 예) `시술 후 붓기·단단함, 정상일까?`
- **큰 제목(line2)**: 메인 키워드가 들어간 한 줄. 14자 안팎. card·ivory 는 `\n` 으로 두 줄까지.
- 글자는 이 두 줄(+card 분류 표시)뿐입니다. 날짜·체크리스트·영문 라벨·칩을 붙이지 않습니다 —
  운영자가 "AI 티 나는 군더더기"로 기각했습니다.
- 의료광고: 효과 단정·최고·유일·전후·가격 수치 금지. 법률: 승소 보장·전관 같은 표현 금지.

## 4. 행마다: 배경 만들기

`gpt-image` 스킬의 bridge 로 만듭니다. 출력은 저장소 `generated-images/` (git 이 무시함).

```bash
cd /home/user/jarvis   # 저장소 루트
node .claude/skills/gpt-image/scripts/gpt_image.mjs generate \
  --prompt "<아래 규칙으로 쓴 영어 프롬프트>" \
  --out "generated-images/lt-<페이지ID 앞 8자>.png"
```

프롬프트에 **반드시** 넣을 것:
- `Photorealistic`, 캔버스 비율(`wide 16:9 landscape`, 1200x900 이면 `wide 4:3 landscape`)
- `view_crops` 로 위아래가 잘리는 고객사면: `the top and bottom N percent may be cropped later, so keep every important element inside the central horizontal band`
  (N = 잘리는 비율. 필라테스는 17)
- 틀별 빈자리: card → `the center is soft, uncluttered blur for a headline card`,
  bottomleft → `subject on the right half; the left half is clean, softly lit background`,
  klavuu → `subject center-right; the top-right corner is plain background; the lower part fades into soft white haze`,
  ivory → `objects in the right half; the left half is calm, warm, uncluttered space`
- 끝에: `No text, no letters, no numbers, no logos, no brand names, no watermark, no needles, no syringes, no medical devices, no before-and-after comparison.`
- 인물은 `Korean`, 자연스러운 피부결, 차분한 표정. 시술 장면·환자처럼 보이는 연출 금지(가상 인물은 분위기용).
- 실제 장비·제품(울쎄라·리쥬란 등)을 그리게 하지 않습니다. 제품은 `unbranded` 로만.

만든 이미지를 **직접 열어 봅니다**. 아래면 버리고 다시 만듭니다(한 행에 최대 2번 더):
글자·숫자·로고가 보임, 손가락·얼굴이 어색함, 바늘·피·상처, 글자 자리를 피사체가 가림.
3번 모두 실패하면 그 행은 건너뛰고 보고합니다.

## 5. 행마다: 글자 얹기 → 확인 → 붙이기

```bash
cd notion-wp-publish
PYTHONPATH=src python3 -m notionwp.longform_thumb render --style card \
  --bg ../generated-images/lt-xxxxxxxx.png --client "<고객사>" \
  --pill "리투오 부작용" --line1 "붓기·단단함, 어디까지 정상일까" --line2 "진료가 필요한 신호" \
  --out ../generated-images/lt-xxxxxxxx-final.png
```

- 로고는 `designs/logos/<고객사>.png` 를 씁니다. 없으면 `--brand "<고객사명>"` 으로 글자를 대신 넣습니다.
- `--accent '#RRGGBB'` 로 card 분류 표시 색·ivory 글자색을 고객사 색에 맞출 수 있습니다(없으면 기본).
- 사이트가 잘라 보여 주는 모습을 만들어 **직접 열어** 봅니다. 잘린 칸에서 글자·로고가
  하나라도 잘리면 붙이지 않습니다(틀이 안전 영역에 맞추므로 정상이면 잘리지 않습니다).

```bash
PYTHONPATH=src python3 -m notionwp.longform_thumb crops --file ../generated-images/lt-xxxxxxxx-final.png --client "<고객사>" --out ../generated-images/lt-xxxxxxxx-crops.png
```

- 결과 PNG 를 **직접 열어** 글자가 사진과 겹쳐 안 읽히거나 로고가 묻히지 않는지 봅니다.
  문제가 있으면 다른 틀로 다시 얹거나 배경을 다시 만듭니다.
- 확인되면 붙입니다. 붙이기 직전에 그 행이 아직 비어 있는 롱폼인지 다시 확인하고,
  사람이 그사이 올렸으면 덮어쓰지 않고 멈춥니다.

```bash
PYTHONPATH=src python3 -m notionwp.longform_thumb attach --page <페이지ID> --file ../generated-images/lt-xxxxxxxx-final.png --client "<고객사>"
```

## 6. 보고

고객사별로 만든 것(제목 · 틀)과 건너뛴 것(사유)을 나눠 짧게 적습니다.
0건이면 "롱폼 썸네일 대상 없음" 한 줄.

## 하지 말 것

- 숏폼·엔티티 행, 이미 썸네일이 있는 행, 설정표·디자인 파일(`designs/`), 기존 썸네일 루틴을 건드리지 않습니다.
- 틀을 새로 만들거나 크기·위치를 바꾸지 않습니다(운영자 확정). 바꾸려면 사람에게 먼저 묻습니다.
- 생성 이미지를 저장소에 커밋하지 않습니다.
