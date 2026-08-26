// 모든 페이지가 함께 쓰는 것들: API 호출, 로그인 모달, 헤더.
export const state = { user: null, quota: null, plans: [], packs: [] };

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || '요청에 실패했습니다.');
    err.status = res.status;
    throw err;
  }
  return data;
}

export async function loadMe() {
  const data = await api('/api/me');
  state.user = data.user;
  state.quota = data.quota;
  state.plans = data.plans;
  state.packs = data.packs;
  state.site = data.site;
  return data;
}

export const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const won = (n) => `${Math.round(Number(n) || 0).toLocaleString('ko-KR')}원`;

/** *행동* 은 기울임, 줄바꿈은 <br> 로 바꿔 대사처럼 보이게 합니다. */
export function renderRoleplay(text) {
  return esc(text)
    .replace(/\*([^*\n]+)\*/g, '<i class="act">$1</i>')
    .replace(/\n/g, '<br>');
}

export function header(active) {
  const user = state.user;
  const links = [
    ['/', '탐색'],
    ['/chat', '내 대화'],
    ['/create', '캐릭터 만들기'],
  ];
  return `<header class="top"><div class="wrap">
    <a class="logo" href="/">💬 캐릭터<b>톡</b></a>
    <nav>
      ${links.map(([href, label]) => `<a href="${href}" class="${active === href ? 'on' : ''}">${label}</a>`).join('')}
      ${user?.isAdmin ? `<a href="/admin" class="${active === '/admin' ? 'on' : ''}">매출</a>` : ''}
      ${
        user
          ? `<a href="/account" class="${active === '/account' ? 'on' : ''}">${esc(user.nickname || user.email)}</a>`
          : `<button class="btn primary sm" data-auth="login">로그인</button>`
      }
    </nav>
  </div></header>`;
}

/** 로그인/가입 모달을 페이지에 붙이고 열고 닫는 기능을 답니다. */
export function mountAuthModal(onSuccess) {
  if (document.getElementById('auth-modal')) return;
  const el = document.createElement('div');
  el.id = 'auth-modal';
  el.className = 'modal';
  el.innerHTML = `<div class="box">
    <div class="tabs">
      <button data-tab="login" class="on">로그인</button>
      <button data-tab="signup">회원가입</button>
    </div>
    <h2 data-title>다시 오셨네요</h2>
    <p class="sub" data-sub>대화를 이어가려면 로그인해주세요.</p>
    <div class="err" data-err hidden></div>
    <form data-form>
      <div class="field" data-nick hidden>
        <label>캐릭터가 부를 이름</label>
        <input type="text" name="nickname" maxlength="20" placeholder="예: 준호" autocomplete="nickname">
      </div>
      <div class="field">
        <label>이메일</label>
        <input type="email" name="email" required autocomplete="email" placeholder="you@example.com">
      </div>
      <div class="field">
        <label>비밀번호</label>
        <input type="password" name="password" required minlength="8" autocomplete="current-password" placeholder="8자 이상">
      </div>
      <button class="btn primary" style="width:100%;margin-top:6px" type="submit" data-submit>로그인</button>
    </form>
    <p class="small muted center" style="margin-top:14px">가입하면 무료로 바로 대화를 시작할 수 있어요.</p>
  </div>`;
  document.body.appendChild(el);

  let mode = 'login';
  const err = el.querySelector('[data-err]');
  const setMode = (next) => {
    mode = next;
    el.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === next));
    el.querySelector('[data-title]').textContent = next === 'login' ? '다시 오셨네요' : '3초 만에 시작하기';
    el.querySelector('[data-sub]').textContent =
      next === 'login' ? '대화를 이어가려면 로그인해주세요.' : '이메일만 있으면 됩니다. 무료 메시지가 바로 지급돼요.';
    el.querySelector('[data-nick]').hidden = next === 'login';
    el.querySelector('[data-submit]').textContent = next === 'login' ? '로그인' : '가입하고 시작하기';
    err.hidden = true;
  };

  el.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.tab)));
  el.addEventListener('click', (e) => { if (e.target === el) el.classList.remove('on'); });

  el.querySelector('[data-form]').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const btn = el.querySelector('[data-submit]');
    btn.disabled = true;
    try {
      const data = await api(`/api/auth/${mode}`, {
        method: 'POST',
        body: {
          email: form.get('email'),
          password: form.get('password'),
          nickname: form.get('nickname') || '',
        },
      });
      state.user = data.user;
      state.quota = data.quota;
      el.classList.remove('on');
      onSuccess?.(data);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      btn.disabled = false;
    }
  });

  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-auth]');
    if (!trigger) return;
    setMode(trigger.dataset.auth === 'signup' ? 'signup' : 'login');
    el.classList.add('on');
    el.querySelector('input[name=email]').focus();
  });
}

export function openAuth(mode = 'login') {
  document.querySelector(`[data-auth="${mode}"]`)?.click();
  const modal = document.getElementById('auth-modal');
  if (modal && !modal.classList.contains('on')) {
    modal.classList.add('on');
  }
}
