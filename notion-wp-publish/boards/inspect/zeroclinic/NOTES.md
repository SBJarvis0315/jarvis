# 제로클리닉 관리자 화면 정찰 (2026-09-09)

`--board-inspect` 를 `https://www.zeroclinic1.com/admin/board/main.php` 로 실행한 결과입니다.
**로그인 단계에서 막혀 목록·글쓰기 폼까지는 들어가지 못했습니다.** 그래서
`inspect.json` 은 만들어지지 않았고(코드가 login → 목록 → 글쓰기 순서로 떠서
로그인에서 예외가 나면 뒤 단계와 리포트 저장까지 못 감), 남은 산출물은 로그인
실패 시점의 스크린샷·HTML 뿐입니다.

## 요약 (한 줄)

로그인 폼·셀렉터·드라이버 로직은 실제 화면과 **맞습니다**. 실패 원인은 두 가지로,
① 서버가 제공된 관리자 **비밀번호를 거부**했고(아이디는 유효), ② 이 실행 환경의
프록시가 Chromium 의 기본 TLS(1.3) 핸드셰이크를 끊어서 `--ssl-version-max=tls1.2`
없이는 페이지에 닿지도 못했습니다.

## 1. 실패 원인 — 자격증명 거부 (주 원인)

로그인 폼을 그대로(브라우저 없이 `curl` 로도) 재현했더니 서버가 세 갈래로 답을
나눕니다. 값은 출력하지 않고 응답만 적습니다.

| 입력 | 서버 alert |
|---|---|
| 제공된 아이디 + 제공된 비밀번호 | `패스워드가 틀립니다.` |
| 제공된 아이디 + 아무 잘못된 비밀번호 | `관리자 비번 확인` |
| 없는 아이디 | `관리자 아이디 확인` |

- **아이디는 유효**합니다 (없는 아이디였다면 `관리자 아이디 확인` 이 떴을 것).
- 제공된 비밀번호는 거부되지만, 무작위 오답(`관리자 비번 확인`)과 **다른 분기**
  (`패스워드가 틀립니다.`)로 떨어집니다. 즉 서버 인증 로직 안에서 이 비밀번호가
  어떤 검사는 통과하고 다른 검사(관리자 승격/2차 비번으로 추정)에서 걸립니다.
  어느 쪽이든 결과는 "비밀번호 거부" 이고, 이는 **드라이버가 고칠 수 있는 문제가
  아니라 환경변수 `BOARD_PASSWORD_ZEROCLINIC1` 값 자체의 문제**입니다.
- 로그인 JS(`/admin/script/common.js`, 폼의 `fnlogin()`)에는 md5/sha/암호화 등
  **클라이언트 측 비밀번호 변환이 전혀 없습니다.** 폼은 원문 그대로 POST 합니다.
  그래서 `curl` 로 원문을 보낸 결과 == Playwright 드라이버가 채워 보낸 결과입니다.
  드라이버가 값을 잘못 다뤄서 실패한 게 아닙니다.

**팀 조치**: `BOARD_PASSWORD_ZEROCLINIC1` 값을 최신 관리자 비밀번호로 갱신해야
합니다. (혹은 이 계정이 `emp_check`=직원 로그인만 되고 관리자 권한이 없다면 관리자
권한이 있는 계정으로 교체.)

## 2. 실패 원인 — 실행 환경의 TLS 프록시 (부차 원인, 코드 아님)

이 원격 세션의 이그레스 프록시는 Chromium 이 기본(TLS 1.3) 으로 접속하면
`ERR_CONNECTION_RESET` 로 끊습니다. `curl` 은 TLS 1.2 로 자동 낙착되어 200 을
받지만, Chromium 은 낙착하지 않아 `www.zeroclinic1.com` 에 **아예 닿지 못했습니다.**
`--ssl-version-max=tls1.2` 로 브라우저를 띄우자 비로소 로그인 페이지가 떴습니다.

- 이번 정찰에서는 `CHROMIUM_PATH` 로 `--ssl-version-max=tls1.2` 를 붙인 래퍼 스크립트를
  물려 우회했습니다. `src/notionwp/board.py` 의 `chromium.launch(...)` 에는 `args` 가
  없어 이 플래그를 넣을 길이 없습니다 — **이 환경에서 실제 발행을 돌리려면 launch 에
  args 를 넣는 손질이 필요**하지만, 이는 사이트가 아니라 실행 환경 특성입니다.
  (요청대로 코드는 고치지 않았습니다.)
- 또 이 프록시는 `code.jquery.com` 을 403 으로 막습니다. 로그인 페이지는 jQuery 를
  `//code.jquery.com/...` 에서 불러오므로, 정찰 때는 라우팅으로 로컬 jQuery(3.7.1)를
  주입해 대체했습니다. 실 서비스 환경이 이 CDN 을 허용한다면 문제 없습니다.

## 3. 실제로 확인한 로그인 폼 동작

로그인 화면 `https://www.zeroclinic1.com/admin/Login.php` (대문자 L, 프로파일과 일치):

- `<form name="Login" method="post" action="/admin/LoginPost.php" onsubmit="return fnlogin();">`
- 아이디 칸: `<input type="text" id="loginid" name="id">`
- 비밀번호 칸: `<input type="password" id="loginpw" name="Pwd">`
- 숨은 필드: `mode=emp_check`, `frompage=`(빈 값)
- 로그인 버튼은 `<button>`/`submit` 이 **아니라** `<a href="javascript:fnlogin();">` 안에
  `로그인` 글자를 담은 `<div>` 입니다.
- **엔터/버튼 둘 다 동작**: 두 입력칸에 `onkeydown` 으로 Enter(keyCode 13) → `fnlogin()`,
  그리고 `<a>` 클릭 → `fnlogin()`. `fnlogin()` 은 빈 값만 검사한 뒤 `document.Login.submit()`.
- 드라이버는 password 칸에 Enter 를 눌러 제출하고, 실패 시 `a:has-text('로그인')` 을
  클릭하는 폴백을 가집니다. **둘 다 이 폼과 호환됩니다.** 셀렉터 문제 아님.

## 4. 프로파일(`boards/www.zeroclinic1.com.json`) 검증

로그인을 못 넘어서 **로그인 뒤 화면(탭·글쓰기 버튼·에디터·글 링크)은 검증 불가**
입니다. 검증 가능한 항목만 확인했고, 모두 실제와 일치해 **데이터 필드는 수정하지
않았습니다** (note 만 이번 정찰 결과로 갱신).

| 필드 | 상태 |
|---|---|
| `login_url` `/admin/Login.php` | ✅ 확인 (200, 비밀번호 칸 존재, 대문자 L) |
| `admin_url` `/admin/board/main.php` | ✅ 존재. 미로그인 시 `<meta refresh>` 로 `/admin/Login.php` 로 보냄 |
| `public_url` `htm/boardseo_read.php?id={id}` | ✅ `?id=1` → 200, 형식 유효 |
| `host` | ✅ 일치 |
| `tab` `블로그` | ⏳ 검증 불가(로그인 뒤) |
| `write_button` `글쓰기` | ⏳ 검증 불가 |
| `submit_buttons` | ⏳ 검증 불가 |
| `id_param` `id` | ⏳ 검증 불가(공개 read 는 `?id=` 를 쓰므로 유력) |
| `labels` (제목/조회수/내용/HTML) | ⏳ 검증 불가 |
| 에디터(서머노트/jQuery/툴바 data-event) | ⏳ 검증 불가 |

로그인 뒤 화면은 전부 세션으로 잠겨 있어(미로그인 접근은 로그인으로 리다이렉트)
공개 경로로는 뜰 수 없습니다. **비밀번호가 갱신되면 이 정찰을 다시 돌려** 위 ⏳
항목을 채워야 합니다.

## 산출물

- `20260909-002425-login-failed.png` / `.html` — 첫 시도(엔터 제출) 실패 화면
- `20260909-002540-login-failed.png` / `.html` — jQuery 로컬 주입 후 재시도 실패 화면
  (스크린샷의 아이디 칸은 일반적인 `admin` 글자, 비밀번호는 가려진 점 표시.
  `.html` 에는 비밀번호 값 없음 — grep 로 확인. `admin` 문자열은 `/admin/` 경로에서만
  매칭됨.)
- `inspect.json` **없음** — 로그인에서 멈춰 리포트 저장 단계에 도달 못 함.

### 원격(브랜치)에 올라간 것 / 로컬에만 있는 것

이 원격 세션에서는 `git push` 가 auto-mode 권한 분류기에 막혀 있고, 환경은
GitHub 쓰기를 GitHub MCP 도구로만 하도록 안내합니다. 그 MCP push 도구는 파일
내용을 문자열로 인라인해야 해서 **바이너리 PNG 스크린샷은 전송이 안 됩니다.**
그래서 브랜치에는 핵심 산출물인 이 **NOTES.md** 와 수정한 **프로파일 JSON** 만
올렸습니다. 위 `*.png` / `*.html` 원본 증거 파일은 세션 로컬 커밋에만 있고 원격에는
없습니다 (비밀번호는 어디에도 없음 — grep 확인). 팀이 `git push` 권한을 열어 로컬
커밋을 그대로 밀면 스크린샷·HTML 까지 함께 올라갑니다.
