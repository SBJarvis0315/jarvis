"""제로클리닉 관리자 화면을 흉내 내는 로컬 웹서버.

실제 사이트는 이 환경에서 열 수 없으므로, 스크린샷과 팀원 스레드로 파악한 구조를
그대로 옮겨 드라이버가 그 위에서 돌아가는지 봅니다.

  · /admin/board/main.php   로그인 전이면 로그인 폼, 후면 글 목록 (글쓰기 버튼 · 탭)
  · /admin/login.php        POST id/pw → 쿠키
  · /admin/board/write.php  글쓰기 폼 (공지 · HTML · 조회수 · 작성일 · 제목 · 내용)
                             서머노트 흉내 에디터: 이미지 버튼 → 파일 → /admin/upload.php,
                             </> 코드 보기 토글
  · /admin/upload.php       POST → {"url": "/files/editor/N.jpg"}

당연히 진짜 서머노트는 아닙니다. 드라이버가 의지하는 DOM 조각(.note-editable,
.note-codable, data-event 버튼, 행 머리글이 있는 <table>)만 있습니다.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USER, PASSWORD = "admin", "secret"


class FakeBoardSite:
    def __init__(self):
        self.posts: list[dict] = [
            {"id": 161, "title": "기존 글 하나", "hit": 700},
        ]
        self.uploads = 0
        self.login_attempts: list[tuple[str, str]] = []
        self._server: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------ 수명

    def start(self) -> str:
        site = self
        self.upload_html_mode = ""

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # 테스트 출력을 조용히
                pass

            def _send(self, body: str, status=HTTPStatus.OK, headers=None, ctype="text/html; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _logged_in(self) -> bool:
                return "sid=ok" in (self.headers.get("Cookie") or "")

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/admin/board/main.php":
                    if not self._logged_in():
                        return self._send(LOGIN_PAGE)
                    return self._send(site.list_page())
                if url.path == "/admin/board/write.php":
                    if not self._logged_in():
                        return self._send(LOGIN_PAGE)
                    return self._send(WRITE_PAGE)
                if url.path.startswith("/files/editor/"):
                    return self._send("", ctype="image/jpeg")
                return self._send("not found", HTTPStatus.NOT_FOUND)

            def do_POST(self):
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)

                if url.path == "/admin/login.php":
                    form = parse_qs(raw.decode("utf-8"))
                    user, pw = form.get("id", [""])[0], form.get("pw", [""])[0]
                    site.login_attempts.append((user, pw))
                    if (user, pw) == (USER, PASSWORD):
                        return self._send(
                            "", HTTPStatus.FOUND,
                            {"Location": "/admin/board/main.php", "Set-Cookie": "sid=ok; Path=/"},
                        )
                    err = "<p class=err>아이디 또는 비밀번호가 틀립니다</p>"
                    return self._send(LOGIN_PAGE.replace("<!--ERR-->", err))

                if url.path == "/admin/upload.php":
                    site.uploads += 1
                    return self._send(
                        json.dumps({"url": f"/files/editor/2026090{site.uploads}.jpg"}),
                        ctype="application/json",
                    )

                if url.path == "/admin/board/write.php":
                    form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                    new_id = max(p["id"] for p in site.posts) + 1
                    site.posts.insert(
                        0,
                        {
                            "id": new_id,
                            "title": form.get("subject", [""])[0],
                            "hit": int(form.get("hit", ["0"])[0] or 0),
                            "content": form.get("content", [""])[0],
                            "html_mode": form.get("html_type", [""])[0],
                            "notice": form.get("notice", [""])[0],
                        },
                    )
                    return self._send("", HTTPStatus.FOUND, {"Location": "/admin/board/main.php"})

                return self._send("not found", HTTPStatus.NOT_FOUND)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    # ------------------------------------------------------------ 화면

    def list_page(self) -> str:
        rows = "\n".join(
            f"<tr><td>{p['id']}</td>"
            f"<td><a href='/admin/board/view.php?id={p['id']}&page=1'>{p['title']}</a></td>"
            f"<td>2026-09-08</td><td>{p['hit']}</td>"
            f"<td><a class='btn' href='/admin/board/write.php?mode=edit&id={p['id']}'>수정</a> "
            f"<a class='btn red' href='#'>삭제</a></td></tr>"
            for p in self.posts
        )
        return f"""<!doctype html><html><head><meta charset=utf-8><title>관리자</title></head><body>
<div class=top><a href='#'>HOME</a> <a href='#'>SITE HOME</a> <a href='/admin/logout.php'>LOG OUT</a></div>
<ul class=nav><li>HOME</li><li>Quick상담</li><li class=on>게시판관리</li></ul>
<ul class=sub><li><a href='/admin/board/main.php?code=news'>제로 소식</a></li>
<li><a href='/admin/board/main.php?code=event'>이벤트</a></li>
<li><a href='/admin/board/main.php?code=seo'>블로그</a></li></ul>
<h2>블로그</h2>
<form method=get action='/admin/board/main.php'>
  <select name=key><option value=subject>제목</option></select>
  <input type=text name=keyword> <input type=submit value=검색>
</form>
<table class=list><thead><tr><th>번호</th><th>제 목</th><th>날짜</th><th>조회</th><th>관리</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class=paging>1 2 3</div>
<a class='btn write' href='/admin/board/write.php'>글쓰기</a>
</body></html>"""


LOGIN_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>로그인</title></head><body>
<h1>ZERO CLINIC 관리자</h1>
<!--ERR-->
<form method=post action='/admin/login.php'>
  <input type=hidden name=ret value='/admin/board/main.php'>
  <p>아이디 <input type=text name=id></p>
  <p>비밀번호 <input type=password name=pw onkeydown="if(event.key==='Enter'){event.preventDefault();}"></p>
  <button type=button onclick="this.form.submit()">로그인</button>
</form></body></html>"""


WRITE_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>글쓰기</title>
<style>.note-codable{display:none}.note-modal{display:none}.note-modal.open{display:block}</style>
</head><body>
<h2>블로그</h2>
<form method=post action='/admin/board/write.php' id=wform>
<table class=write>
<tr><th>공지</th><td><label><input type=radio name=notice value=0 checked>일반</label> <label><input type=radio name=notice value=1>공지</label></td></tr>
<tr><th>HTML</th><td><label><input type=radio name=html_type value=html checked>HTML</label> <label><input type=radio name=html_type value=htmlbr>HTML+BR</label> <label><input type=radio name=html_type value=text>텍스트</label></td></tr>
<tr><th>조회수</th><td><input type=text name=hit></td></tr>
<tr><th>작성일</th><td><input type=text name=wdate value='2026-09-09 08:19:54'><br>예)2026-09-09 08:19:54</td></tr>
<tr><th>제목</th><td><input type=text name=subject style='width:90%'></td></tr>
<tr><th>내용</th><td>
  <textarea name=content style='display:none'></textarea>
  <div class=note-editor>
    <div class=note-toolbar>
      <button type=button data-event=bold>B</button>
      <button type=button data-event=showImageDialog>이미지</button>
      <button type=button data-event=codeview>&lt;/&gt;</button>
    </div>
    <div class=note-editing-area>
      <textarea class=note-codable></textarea>
      <div class=note-editable contenteditable=true><p><br></p></div>
    </div>
  </div>
  <div class=note-modal>
    <button type=button class=close>×</button>
    <input type=file class=note-image-input>
  </div>
</td></tr>
</table>
<input type=submit value=등록> <a href='/admin/board/main.php'>목록</a>
</form>
<script>
(function(){
  var editable = document.querySelector('.note-editable');
  var codable = document.querySelector('.note-codable');
  var hidden = document.querySelector('textarea[name=content]');
  var modal = document.querySelector('.note-modal');
  var codeview = false;

  document.querySelector('[data-event=codeview]').addEventListener('click', function(){
    codeview = !codeview;
    if (codeview) { codable.value = editable.innerHTML; codable.style.display = 'block'; editable.style.display = 'none'; }
    else { editable.innerHTML = codable.value; codable.style.display = 'none'; editable.style.display = 'block'; }
  });
  document.querySelector('[data-event=showImageDialog]').addEventListener('click', function(){ modal.classList.add('open'); });
  modal.querySelector('.close').addEventListener('click', function(){ modal.classList.remove('open'); });

  document.querySelector('.note-image-input').addEventListener('change', function(ev){
    var file = ev.target.files[0];
    var fd = new FormData(); fd.append('file', file);
    fetch('/admin/upload.php', {method: 'POST', body: fd}).then(function(r){ return r.json(); }).then(function(j){
      var img = document.createElement('img'); img.src = j.url; editable.appendChild(img);
      modal.classList.remove('open');
    });
  });

  document.getElementById('wform').addEventListener('submit', function(){
    if (codeview) { editable.innerHTML = codable.value; }
    hidden.value = editable.innerHTML;
  });
})();
</script>
</body></html>"""
