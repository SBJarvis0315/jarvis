// 서버를 실제로 띄워서 가입 → 대화 → 결제 → 매출 확인까지 한 번에 훑습니다.
import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const PORT = 3411;
const base = `http://127.0.0.1:${PORT}`;
let child;
let dir;
let cookie = '';

async function call(path, { method = 'GET', body, raw = false } = {}) {
  const res = await fetch(base + path, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(cookie ? { Cookie: cookie } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const setCookie = res.headers.getSetCookie?.()[0];
  if (setCookie) cookie = setCookie.split(';')[0];
  if (raw) return res;
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

before(async () => {
  dir = mkdtempSync(join(tmpdir(), 'chartalk-'));
  child = spawn(process.execPath, ['--disable-warning=ExperimentalWarning', 'src/server.js'], {
    env: { ...process.env, PORT: String(PORT), DB_PATH: join(dir, 'test.db'), DEMO_MODE: '1', ANTHROPIC_API_KEY: '', TOSS_SECRET_KEY: '' },
    stdio: 'ignore',
  });
  for (let i = 0; i < 60; i++) {
    try {
      await fetch(base + '/api/me');
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 100));
    }
  }
  throw new Error('서버가 뜨지 않았습니다.');
});

after(() => {
  child?.kill();
  rmSync(dir, { recursive: true, force: true });
});

describe('전체 흐름', () => {
  test('첫 화면과 공식 캐릭터가 제공된다', async () => {
    const page = await call('/', { raw: true });
    assert.equal(page.status, 200);
    assert.match(await page.text(), /AI 캐릭터와 나누는 진짜 같은 대화/);

    const { data } = await call('/api/characters');
    assert.ok(data.characters.length >= 8);
    assert.ok(data.characters.every((c) => c.persona === undefined), '남의 캐릭터 설정이 노출되면 안 됩니다');
    assert.ok(data.tags.length > 0);
  });

  test('로그인 없이 대화하면 401', async () => {
    const { status } = await call('/api/conversations', { method: 'POST', body: { characterSlug: 'yuri' } });
    assert.equal(status, 401);
  });

  test('가입 → 캐릭터와 대화 → 사용량 차감', async () => {
    const signup = await call('/api/auth/signup', {
      method: 'POST',
      body: { email: 'tester@example.com', password: 'password1', nickname: '테스터' },
    });
    assert.equal(signup.status, 201);
    assert.equal(signup.data.user.plan, 'free');

    const created = await call('/api/conversations', { method: 'POST', body: { characterSlug: 'yuri' } });
    assert.equal(created.status, 201);
    assert.equal(created.data.messages.length, 1, '첫 인사말이 들어 있어야 합니다');
    assert.equal(created.data.messages[0].role, 'assistant');

    const id = created.data.conversation.id;
    const res = await call(`/api/conversations/${id}/messages`, {
      method: 'POST',
      body: { message: '오랜만이야' },
      raw: true,
    });
    assert.equal(res.status, 200);
    const stream = await res.text();
    assert.match(stream, /event: delta/);
    assert.match(stream, /event: done/);

    const after = await call(`/api/conversations/${id}`);
    assert.equal(after.data.messages.length, 3);
    assert.equal(after.data.messages[2].role, 'assistant');

    const me = await call('/api/me');
    assert.ok(me.data.quota.usedKrw > 0, '사용량이 기록돼야 합니다');
    assert.equal(me.data.quota.messagesSent, 1);
    assert.ok(me.data.quota.messagesLeft <= me.data.quota.monthlyMessages);
    assert.ok(me.data.quota.remainingKrw < me.data.quota.capKrw);
  });

  test('빈 메시지는 거절한다', async () => {
    const { conversations } = (await call('/api/conversations')).data;
    const { status } = await call(`/api/conversations/${conversations[0].id}/messages`, { method: 'POST', body: { message: '   ' } });
    assert.equal(status, 400);
  });

  test('무료 플랜은 캐릭터를 만들 수 없고, 결제 후에는 만들 수 있다', async () => {
    const denied = await call('/api/characters', {
      method: 'POST',
      body: { name: '내캐릭', persona: '스물다섯 살 무뚝뚝한 바리스타입니다.', greeting: '어서오세요' },
    });
    assert.equal(denied.status, 402);

    const paid = await call('/api/billing/register', { method: 'POST', body: { planId: 'lite' } });
    assert.equal(paid.status, 200);
    assert.equal(paid.data.user.plan, 'lite');

    const created = await call('/api/characters', {
      method: 'POST',
      body: { name: '내캐릭', persona: '스물다섯 살 무뚝뚝한 바리스타입니다.', greeting: '어서오세요', tags: '일상' },
    });
    assert.equal(created.status, 201);
    assert.equal(created.data.character.mine, true);
  });

  test('충전하면 한도가 늘어난다', async () => {
    const before = (await call('/api/me')).data.quota.capKrw;
    const { status, data } = await call('/api/billing/topup', { method: 'POST', body: { packId: 'large' } });
    assert.equal(status, 200);
    assert.equal(data.quota.capKrw, before + data.capKrw);
  });

  test('첫 가입자는 관리자로 매출 대시보드를 본다', async () => {
    const { status, data } = await call('/api/admin/stats');
    assert.equal(status, 200);
    assert.equal(data.goalKrw, 300000);
    assert.ok(data.revenueKrw > 0);
    assert.equal(data.paidUsers, 1);
  });

  test('다른 사람의 대화는 볼 수 없다', async () => {
    const mine = (await call('/api/conversations')).data.conversations[0].id;
    cookie = '';
    await call('/api/auth/signup', { method: 'POST', body: { email: 'other@example.com', password: 'password1' } });
    const peek = await call(`/api/conversations/${mine}`);
    assert.equal(peek.status, 404);
    const admin = await call('/api/admin/stats');
    assert.equal(admin.status, 403);
  });
});
