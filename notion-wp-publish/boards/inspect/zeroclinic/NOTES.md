# 제로클리닉 관리자 화면 정찰 결과 (2026-09-09)

**실제 관리자에 로그인해 확인한 기록입니다.** 아래 내용은 추정이 아니라 실물에서 읽은
값이며, `boards/www.zeroclinic1.com.json` 프로파일과 `src/notionwp/board.py` 를 여기에
맞춰 고쳤습니다.

## 0. 로그인이 두 번 막혔던 이유 — 환경변수의 `#`

`BOARD_PASSWORD_ZEROCLINIC1` 값이 서버에 닿기 전에 잘려 있었습니다. 환경변수 입력칸이
`.env` 형식이라 `#` 뒤를 주석으로 버리는데, 이 계정의 비밀번호가 `#` 로 끝납니다.

같은 폼에 값을 직접 보내 비교한 결과입니다 (값 자체는 기록하지 않습니다).

| 보낸 비밀번호 | 서버 응답 |
|---|---|
| 온전한 값 | `관리자 로그인 되었습니다.` → `/admin/board/main.php` 로 이동 |
| `#` 가 잘린 값 | `패스워드가 틀립니다.` |

**교훈**: 값에 `#` 이 들어가면 따옴표로 감싸 넣어야 합니다. 감싼 따옴표는 코드가
벗겨 냅니다(`config._unquote`). 그래도 잘리면 입력칸이 따옴표 안까지 자르는 것이므로
그 사실을 사람에게 알려야 합니다.

## 1. 블로그 게시판은 `main.php` 가 아니라 `boardseo_list.php`

`/admin/board/main.php` 는 대시보드(호스팅 안내가 뜨는 첫 화면)입니다. 발행 대상 게시판은
**게시판관리 › 블로그 = `/admin/board/boardseo_list.php`** 이며 내부 테이블 이름은
`boardseo` 입니다. 팀원 스레드의 "seo 게시판 → 블로그로 이름 변경"이 이것입니다.

메뉴에 `blog_list.php` 라는 **같은 이름의 다른 게시판**이 또 있습니다. 비어 있고 쓰지
않으므로 절대 이쪽으로 가면 안 됩니다.

관리자 메뉴 전체: 게시판관리(제로 소식 · 이벤트 · WITH STAR · 제로 TV · 유튜브/TV ·
블로그 · 언론보도 · **블로그(=boardseo)** · 시술 후 주의사항 · 중국 유튜브) / 회원관리 /
기본관리(홈페이지 설정 · 메타태그 · 게시판설정 · 약관 · 네이버캐러셀) / 통계관리 /
기타관리(슬라이드 · 팝업 · 리얼 셀피 등).

## 2. 목록 화면

- 표 열: 번호 · 제목 · 날짜 · 조회 · 관리(수정/삭제)
- 글 링크: `boardseo_read.php?id=<진짜ID>&fakeid=<화면번호>` — **번호 열은 화면용이고
  주소에 쓰이는 것은 진짜 ID 입니다.** 예: 화면 278 = id 315.
- 수정 링크: `boardseo_write.php?wmode=modify&id=<진짜ID>&…`
- 공개 글 주소도 진짜 ID 를 씁니다: `https://www.zeroclinic1.com/htm/boardseo_read.php?id=<진짜ID>`
- 검색: `<input name="keyword">` + `<select name="key">` (제목)
- 글쓰기 버튼: `<a href="boardseo_write.php?…"><img alt="글쓰기"></a>` — 글자가 아니라
  그림이지만 alt 덕분에 이름으로 찾을 수 있습니다.
- 실제 조회수 분포는 682~1007 이었습니다. 프로파일의 500~1100 범위와 맞습니다.

## 3. 글쓰기 폼 (`boardseo_write.php`)

`<form action="boardseo_write_ok.php" method="post" enctype="multipart/form-data" name="wform">`

| 행 머리글 | 입력칸 | 비고 |
|---|---|---|
| 공지 | `isnoti` 라디오 `N`(일반, 기본) / `Y`(공지) | 일반 그대로 둡니다 |
| HTML | `ishtml` 라디오 `Y`(HTML, 기본) / `YB`(HTML+BR) / `N`(텍스트) | **값으로 고릅니다** |
| 조회수 | `visited` (텍스트) | 비어 있음. 500~1100 임의값을 넣습니다 |
| 작성일 | `udate` (텍스트) | 현재시각이 이미 채워져 있어 건드리지 않습니다 |
| 제목 | `subject` (텍스트) | |
| 내용 | `contents1` (`#summernote`) + `contents` (`#editorcontent`, 숨김) | 아래 참고 |
| 이미지 | `attach1`~`attach3` (파일) | 별도 첨부칸. 본문 이미지에는 쓰지 않습니다 |

**등록 버튼은 글자가 아니라 그림입니다.**
`<a href="javascript:checkForm();"><img src="../img/btn/writeok.gif" alt="글쓰기"></a>`
그래서 프로파일에 `submit_selector: "a[href*='checkForm']"` 를 두고 그것으로 집습니다.

`checkForm()` 의 순서: 제목 빈 값 검사 → `$('#summernote').summernote('code')` 를
`#editorcontent`(name=`contents`) 에 복사 → 본문 빈 값 검사 → `frm.submit()`.
즉 **서버가 읽는 본문은 `contents`** 이고, 서머노트에 넣은 내용이 그대로 넘어갑니다.

## 4. 에디터

- 서머노트 **0.8.18**, 사이트가 직접 호스팅합니다 (`/summernote-0.8.18-dist/summernote-lite.js`).
- jQuery 3.5.1 은 **`code.jquery.com`** 에서 받습니다 → 허용 도메인에 필요합니다(추가 완료).
- 툴바: fontname · fontsize · bold/italic/underline/clear · color · table · ul/ol/paragraph ·
  link/**picture** · **codeview**/help
- 이미지 업로드는 `onImageUpload` 콜백이 `/summernote-0.8.18-dist/file_uploader.php` 로
  `file[]` multipart 를 보내고, 돌아온 주소를 본문에 `<img>` 로 꽂습니다. 드라이버가
  그림 버튼 → 파일 선택 → 주소 회수 로 쓰는 경로와 같습니다.
- `cdn.jsdelivr.net` 은 나눔바른고딕 CSS 한 줄에만 쓰입니다. 막혀도 동작에 지장 없습니다.

## 5. 실행 환경 (사이트가 아니라 우리 쪽 사정)

- 이그레스 프록시가 TLS 1.3 핸드셰이크를 끊습니다. `curl` 은 1.2 로 내려가지만 Chromium 은
  내려가지 않아 사이트에 닿지 못합니다 → `chromium_args()` 가 프록시 뒤에서
  `--ssl-version-max=tls1.2` 를 붙입니다.
- 허용 도메인에 `www.zeroclinic1.com` 과 `code.jquery.com` 이 필요합니다(둘 다 추가 완료).

## 6. 아직 실제로 해 보지 않은 것

로그인·목록·글쓰기 화면 구조까지는 실물에서 확인했지만, **실제 등록(글 올리기)과
이미지 업로드는 하지 않았습니다.** 남의 게시판에 시험 글을 남기지 않기 위해서입니다.
그 두 단계는 같은 마크업을 그대로 옮긴 `tests/fake_board_site.py` 위에서 Chromium 으로
검증했습니다. 첫 실전 발행 때 이 부분을 확인해야 합니다.
