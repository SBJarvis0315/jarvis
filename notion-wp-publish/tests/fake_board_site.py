"""제로클리닉 관리자 화면을 흉내 내는 로컬 웹서버.

실제 사이트는 로그인이 필요하고 테스트가 남의 서버를 두드려서도 안 되므로, 2026-09-09
실제 관리자에 로그인해 확인한 마크업을 그대로 옮겨 둡니다. 필드 이름·버튼 모양·에디터
초기화 방식이 실물과 같아서, 여기서 도는 드라이버는 실물에서도 돕니다.

  · /admin/Login.php            로그인 폼 (id · Pwd, 버튼은 그림을 담은 <a>)
  · /admin/LoginPost.php        POST → 쿠키
  · /admin/board/boardseo_list.php   블로그 목록 (글쓰기 그림 버튼 · keyword 검색)
  · /admin/board/boardseo_write.php  글쓰기 폼
  · /admin/board/boardseo_write_ok.php  등록 처리
  · /summernote-0.8.18-dist/file_uploader.php  에디터 이미지 업로드

실물과 다른 점: 서머노트 대신 최소 스텁을 씁니다(네트워크 없이 실제 서머노트를 받을 수
없음). 스텁도 실물처럼 `$('#summernote').summernote('code')` 를 지원하므로 드라이버의
서머노트 API 경로가 그대로 검증됩니다. `jquery=False` 로 만들면 그 스텁이 빠져서
코드 보기(</>) 폴백 경로를 검증합니다.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USER, PASSWORD = "admin", "P@ssw0rd!"


class FakeBoardSite:
    def __init__(self, *, jquery: bool = True):
        #: 실물처럼 진짜 id 와 화면 번호(fakeid)가 따로 놉니다.
        self.posts: list[dict] = [
            {"id": 161, "fakeid": 124, "title": "기존 글 하나", "visited": 700},
        ]
        self.jquery = jquery
        self.uploads = 0
        self.login_attempts: list[tuple[str, str]] = []
        self._server: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------ 수명

    def start(self) -> str:
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # 테스트 출력을 조용히
                pass

            def _send(self, body, status=HTTPStatus.OK, headers=None, ctype="text/html; charset=utf-8"):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _logged_in(self) -> bool:
                return "sid=ok" in (self.headers.get("Cookie") or "")

            def _guard(self, page: str):
                # 실물처럼 미로그인 접근은 로그인 화면으로 되돌립니다.
                if not self._logged_in():
                    return self._send(LOGIN_PAGE)
                return self._send(page)

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/admin/Login.php", "/admin/login.php"):
                    return self._send(LOGIN_PAGE)
                if path == "/admin/board/boardseo_list.php":
                    return self._guard(site.list_page())
                if path == "/admin/board/boardseo_write.php":
                    return self._guard(site.write_page())
                if path.startswith("/files/editor/"):
                    return self._send(b"", ctype="image/jpeg")
                return self._send("not found", HTTPStatus.NOT_FOUND)

            def do_POST(self):
                path = urlparse(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)

                if path == "/admin/LoginPost.php":
                    form = parse_qs(raw.decode("utf-8"))
                    user, pw = form.get("id", [""])[0], form.get("Pwd", [""])[0]
                    site.login_attempts.append((user, pw))
                    if (user, pw) == (USER, PASSWORD):
                        return self._send(
                            "",
                            HTTPStatus.FOUND,
                            {
                                "Location": "/admin/board/boardseo_list.php",
                                "Set-Cookie": "sid=ok; Path=/",
                            },
                        )
                    return self._send(LOGIN_PAGE.replace("<!--ERR-->", ALERT_WRONG_PW))

                if path == "/summernote-0.8.18-dist/file_uploader.php":
                    site.uploads += 1
                    return self._send(
                        json.dumps({"url": f"/files/editor/2026090{site.uploads}.jpg"}),
                        ctype="application/json",
                    )

                if path == "/admin/board/boardseo_write_ok.php":
                    form = _multipart_fields(raw, self.headers.get("Content-Type", ""))
                    new_id = max(p["id"] for p in site.posts) + 1
                    site.posts.insert(
                        0,
                        {
                            "id": new_id,
                            "fakeid": new_id - 37,
                            "title": form.get("subject", ""),
                            "visited": int(form.get("visited") or 0),
                            "contents": form.get("contents", ""),
                            "ishtml": form.get("ishtml", ""),
                            "isnoti": form.get("isnoti", ""),
                            "udate": form.get("udate", ""),
                        },
                    )
                    return self._send(
                        "", HTTPStatus.FOUND, {"Location": "/admin/board/boardseo_list.php"}
                    )

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
            f"<tr><td>{p['fakeid']}</td>"
            f"<td><a href='boardseo_read.php?id={p['id']}&fakeid={p['fakeid']}&page=1'>"
            f"{p['title']}</a></td>"
            f"<td>2026-09-09</td><td>{p['visited']}</td>"
            f"<td><a href='boardseo_write.php?wmode=modify&id={p['id']}&page=1'>"
            f"<img src='../img/btn/modi.gif' alt='수정'></a></td></tr>"
            for p in self.posts
        )
        return f"""<!doctype html><html><head><meta charset=utf-8>
<title>::: 제로클리닉 관리자페이지 :::</title></head><body>
<div class=top><a href='#'>HOME</a> <a href='/admin/Logout.php'>LOG OUT</a></div>
<div class=mainmenu><ul><li>게시판관리<ul class=submenu>
<li><a href='notice_list.php'>제로 소식</a></li>
<li><a href='boardseo_list.php'>블로그</a></li></ul></li></ul></div>
<h2>블로그</h2>
<form method=get action='boardseo_list.php'>
  <select name=key><option value=subject>제목</option></select>
  <input class=input name=keyword type=text value=""> <input type=submit value=검색>
</form>
<table class=list><thead><tr><th>번호</th><th>제 목</th><th>날짜</th><th>조회</th><th>관리</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class=paging>1 2 3</div>
<table><tr><td align=right>
  <a href="boardseo_write.php?cid=&mode=&key=&keyword=&page=1"><img src="../img/btn/write.gif" align="absmiddle" alt="글쓰기" /></a>
</td></tr></table>
</body></html>"""

    def write_page(self) -> str:
        return WRITE_PAGE.replace("<!--JQ-->", SUMMERNOTE_STUB if self.jquery else "")


ALERT_WRONG_PW = "<script>alert('패스워드가 틀립니다.');</script>"

LOGIN_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>로그인</title></head><body>
<h1>Admin 로그인</h1>
<!--ERR-->
<form name="Login" id="Login" method="post" action="/admin/LoginPost.php" onsubmit="return fnlogin();">
  <input type=hidden value=emp_check name=mode>
  <input type=hidden name=frompage>
  <input type="text" id="loginid" name="id" placeholder="아이디를 입력해 주세요."
         onKeyDown="if(event.keyCode==13){return fnlogin();}">
  <input type="password" id="loginpw" name="Pwd" placeholder="비밀번호를 입력해 주세요."
         onKeyDown="if(event.keyCode==13){return fnlogin();}">
  <a href="javascript:fnlogin();"><div class=btn>로그인</div></a>
</form>
<script>
function fnlogin(){
  var f = document.Login;
  if (f.id.value == "") { alert("아이디를 입력하세요."); return false; }
  if (f.Pwd.value == "") { alert("비밀번호를 입력하세요."); return false; }
  HTMLFormElement.prototype.submit.call(f);
  return false;
}
</script>
</body></html>"""


#: 실물의 서머노트 0.8.18 대신 쓰는 최소 스텁. 드라이버가 실제로 부르는 것만 있습니다.
SUMMERNOTE_STUB = """
<script>
window.jQuery = window.$ = function (sel) {
  var nodes = typeof sel === 'string' ? document.querySelectorAll(sel) : [sel];
  var api = {
    length: nodes.length,
    0: nodes[0],
    first: function () { return api; },
    prev: function () { return window.jQuery(nodes[0] && nodes[0].previousElementSibling); },
    val: function (v) {
      if (nodes[0]) { if (v === undefined) return nodes[0].value; nodes[0].value = v; }
      return api;
    },
    summernote: function (a, b) {
      var editable = document.querySelector('.note-editable');
      if (a === 'code') {
        if (b === undefined) return editable.innerHTML;
        editable.innerHTML = b;
        return api;
      }
      if (a === 'isEmpty') return editable.innerText.trim() === '';
      return api;
    }
  };
  return api;
};
window.jQuery.fn = { summernote: true };
</script>"""


WRITE_PAGE = """<!doctype html><html><head><meta charset=utf-8><title>글쓰기</title>
<style>.note-codable{display:none}.note-modal{display:none}.note-modal.open{display:block}</style>
</head><body>
<h2>블로그</h2>
<form action="boardseo_write_ok.php" method="post" enctype="multipart/form-data" name="wform"
      OnSubmit="return checkForm(this)">
<table class=write>
<tr><th height="25">공지</th><td>
  <input type="hidden" name="mode" value="">
  <input type="hidden" name="page" value="1">
  <input name="isnoti" type="radio" class="bn" value="N" checked> 일반
  <input name="isnoti" type="radio" class="bn" value="Y"> 공지
</td></tr>
<tr><th height="25">HTML</th><td>
  <input name="ishtml" type="radio" class="bn" value="Y" checked> HTML
  <input name="ishtml" type="radio" class="bn" value="YB"> HTML+BR
  <input name="ishtml" type="radio" class="bn" value="N"> 텍스트
</td></tr>
<tr><th height="25">조회수</th><td><input type="text" name="visited" class="input" value=""></td></tr>
<tr><th height="25">작성일</th><td>
  <input name="udate" type="text" class="input" size="19" value="2026-09-09 10:24:17">
</td></tr>
<tr><th height="25">제목</th><td><input name="subject" type="text" class="input" value=""></td></tr>
<tr><th height="25">내용</th><td>
  <textarea name="contents1" id="summernote" class="summernote" style="display:none"></textarea>
  <textarea name="contents" id="editorcontent" style="display: none;"></textarea>
  <div class=note-editor>
    <div class=note-toolbar>
      <button type=button data-event=bold>B</button>
      <button type=button data-event=showImageDialog><i class=note-icon-picture></i></button>
      <button type=button data-event=codeview>&lt;/&gt;</button>
    </div>
    <div class=note-editing-area>
      <textarea class=note-codable></textarea>
      <div class=note-editable contenteditable=true><p><br></p></div>
    </div>
  </div>
  <div class=note-modal>
    <button type=button class=close>x</button>
    <input type=file class=note-image-input>
  </div>
</td></tr>
<tr><th height="25">이미지</th><td><input name="attach1" type="file" class="finput"></td></tr>
</table>
<table><tr><td align=center>
  <a href="javascript:checkForm();"><img src="../img/btn/writeok.gif" align="absmiddle" alt="글쓰기" /></a>
  <a href="javascript:history.go(-1)"><img src="../img/btn/canc.gif" align="absmiddle" alt="취소" /></a>
</td></tr></table>
</form>
<!--JQ-->
<script>
(function(){
  var editable = document.querySelector('.note-editable');
  var codable = document.querySelector('.note-codable');
  var modal = document.querySelector('.note-modal');
  var codeview = false;

  document.querySelector('[data-event=codeview]').addEventListener('click', function(){
    codeview = !codeview;
    if (codeview) { codable.value = editable.innerHTML; codable.style.display='block'; editable.style.display='none'; }
    else { editable.innerHTML = codable.value; codable.style.display='none'; editable.style.display='block'; }
  });
  document.querySelector('[data-event=showImageDialog]').addEventListener('click', function(){
    modal.classList.add('open');
  });
  modal.querySelector('.close').addEventListener('click', function(){ modal.classList.remove('open'); });

  document.querySelector('.note-image-input').addEventListener('change', function(ev){
    var fd = new FormData(); fd.append('file[]', ev.target.files[0]);
    fetch('/summernote-0.8.18-dist/file_uploader.php', {method:'POST', body: fd})
      .then(function(r){ return r.json(); })
      .then(function(j){
        var img = document.createElement('img'); img.src = j.url; editable.appendChild(img);
        modal.classList.remove('open');
      });
  });

  // 실물의 checkForm() 과 같은 순서로 동작합니다.
  window.checkForm = function(){
    var frm = document.wform;
    if (frm.subject.value == "") { alert("제목을 입력해 주십시요."); return false; }
    if (codeview) { editable.innerHTML = codable.value; }
    if (editable.innerText.trim() === "") { alert("내용을 입력하세요"); return false; }
    document.getElementById('editorcontent').value = editable.innerHTML;
    HTMLFormElement.prototype.submit.call(frm);
  };
})();
</script>
</body></html>"""


def _multipart_fields(raw: bytes, content_type: str) -> dict[str, str]:
    """등록 폼은 multipart 로 오므로 필요한 텍스트 필드만 꺼냅니다."""
    if "multipart/form-data" not in content_type:
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()}

    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    fields: dict[str, str] = {}
    for part in raw.split(f"--{boundary}".encode()):
        head, _, body = part.partition(b"\r\n\r\n")
        if b'name="' not in head:
            continue
        name = head.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
        fields[name] = body.rstrip(b"\r\n-").decode("utf-8", "replace")
    return fields
