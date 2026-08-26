import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { resetDbForTest, getDb } from '../src/db.js';
import { hashPassword, verifyPassword, validateSignup, createUser, login, createSession, userFromSession } from '../src/auth.js';
import { PLANS, costKrw } from '../src/config.js';
import { quotaStatus, recordUsage, effectivePlanId, monthRange, estimatedMessageCost } from '../src/quota.js';
import { createCharacter, validateCharacter, uniqueSlug, buildSystemPrompt, listCharacters, toggleLike, publicCharacter } from '../src/characters.js';
import { seedCharacters } from '../src/seed.js';
import { toApiMessages } from '../src/routes/chat.js';
import { registerBillingKey, charge, buyTopup, activatePlan, cancelAtPeriodEnd, runRenewals } from '../src/billing.js';
import { dashboard } from '../src/stats.js';

const makeUser = (email = 'a@b.com') => createUser({ email, password: 'password1', nickname: '준호' });

beforeEach(() => resetDbForTest());

describe('계정', () => {
  test('비밀번호 해시는 원문을 담지 않고 검증된다', () => {
    const stored = hashPassword('password1');
    assert.ok(!stored.includes('password1'));
    assert.equal(verifyPassword('password1', stored), true);
    assert.equal(verifyPassword('password2', stored), false);
  });

  test('가입 입력을 검증한다', () => {
    assert.deepEqual(validateSignup({ email: 'a@b.com', password: 'password1' }), []);
    assert.equal(validateSignup({ email: 'nope', password: 'password1' }).length, 1);
    assert.equal(validateSignup({ email: 'a@b.com', password: 'short' }).length, 1);
  });

  test('닉네임을 비우면 이메일 앞부분을 쓴다', () => {
    const user = createUser({ email: 'Mina@Example.com', password: 'password1' });
    assert.equal(user.email, 'mina@example.com');
    assert.equal(user.nickname, 'mina');
  });

  test('로그인과 세션이 이어진다', () => {
    makeUser();
    assert.equal(login({ email: 'a@b.com', password: 'wrongpass' }), null);
    const user = login({ email: 'a@b.com', password: 'password1' });
    const { token } = createSession(user.id);
    assert.equal(userFromSession(token).id, user.id);
    assert.equal(userFromSession('없는토큰'), null);
  });
});

describe('사용량 한도', () => {
  test('원가가 상한에 닿으면 더 못 쓴다', () => {
    const user = makeUser();
    assert.equal(quotaStatus(user).allowed, true);
    recordUsage({ userId: user.id, model: 'claude-haiku-4-5', usage: { input_tokens: 2_000_000, output_tokens: 0 } });
    const status = quotaStatus(user);
    assert.equal(status.allowed, false);
    assert.equal(status.messagesLeft, 0);
  });

  test('충전팩을 사면 이번 달 한도가 늘어난다', async () => {
    let user = makeUser();
    await registerBillingKey({ user, authKey: 'x' });
    user = getDb().prepare('SELECT * FROM users WHERE id = ?').get(user.id);
    const before = quotaStatus(user).capKrw;
    await buyTopup({ user, packId: 'small' });
    assert.equal(quotaStatus(user).capKrw, before + 1200);
  });

  test('유료 플랜은 만료되면 무료로 떨어진다', () => {
    const user = makeUser();
    getDb().prepare("UPDATE users SET plan='pro', plan_expires_at=? WHERE id=?")
      .run(new Date(Date.now() + 86400_000).toISOString(), user.id);
    assert.equal(effectivePlanId(getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id)), 'pro');
    getDb().prepare('UPDATE users SET plan_expires_at=? WHERE id=?')
      .run(new Date(Date.now() - 1000).toISOString(), user.id);
    assert.equal(effectivePlanId(getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id)), 'free');
  });

  test('이번 달 범위는 한국 시간 1일 0시에서 시작한다', () => {
    const { start, label } = monthRange(new Date('2026-08-15T00:00:00Z'));
    assert.equal(label, '2026-08');
    assert.equal(start, '2026-07-31 15:00:00'); // KST 8월 1일 0시 = UTC 7월 31일 15시
  });

  test('모든 유료 플랜은 원가 상한이 가격보다 낮다(마진 보장)', () => {
    for (const plan of Object.values(PLANS)) {
      if (!plan.priceKrw) continue;
      assert.ok(plan.costCapKrw < plan.priceKrw * 0.5, `${plan.name} 플랜의 마진이 50% 미만입니다`);
    }
  });

  test('메시지당 예상 원가는 모델 요금표를 따른다', () => {
    const perMessage = estimatedMessageCost(PLANS.lite);
    const expected = costKrw({ model: PLANS.lite.model, inputTokens: 2600, outputTokens: Math.round(PLANS.lite.maxTokens * 0.6) });
    assert.equal(perMessage, expected);
  });
});

describe('캐릭터', () => {
  test('필수 항목을 검증한다', () => {
    assert.equal(validateCharacter({ name: '유리', persona: '스물둘 대학생. 소꿉친구이고 무뚝뚝하다.', greeting: '안녕' }).length, 0);
    assert.ok(validateCharacter({ name: '', persona: '짧음', greeting: '' }).length >= 2);
  });

  test('같은 이름이어도 slug 는 겹치지 않는다', () => {
    createCharacter({ name: '유리', persona: '스물둘 대학생. 소꿉친구이고 무뚝뚝하다.', greeting: '안녕' }, null);
    assert.equal(uniqueSlug('유리'), '유리-2');
  });

  test('시스템 프롬프트에 안전 규칙과 사용자 페르소나가 함께 들어간다', () => {
    seedCharacters();
    const character = listCharacters({})[0];
    const prompt = buildSystemPrompt(character, { nickname: '준호', persona: '대학원생' });
    assert.match(prompt, /미성년자/);
    assert.match(prompt, /준호/);
    assert.match(prompt, /대학원생/);
    assert.match(prompt, new RegExp(character.name));
  });

  test('비공개 캐릭터는 남의 목록에 보이지 않는다', () => {
    const owner = makeUser('owner@b.com');
    const other = makeUser('other@b.com');
    createCharacter({ name: '비밀', persona: '아주 비밀스러운 설정입니다요오.', greeting: '안녕', is_public: false }, owner.id);
    assert.equal(listCharacters({ viewerId: other.id }).length, 0);
    assert.equal(listCharacters({ viewerId: owner.id }).length, 1);
  });

  test('좋아요는 토글되고 수가 유지된다', () => {
    const user = makeUser();
    const c = createCharacter({ name: '유리', persona: '스물둘 대학생. 소꿉친구이고 무뚝뚝하다.', greeting: '안녕' }, null);
    assert.equal(toggleLike(user.id, c.id), true);
    assert.equal(toggleLike(user.id, c.id), false);
    assert.equal(getDb().prepare('SELECT like_count FROM characters WHERE id=?').get(c.id).like_count, 0);
  });

  test('남의 캐릭터에는 설정 원문을 내려주지 않는다', () => {
    const owner = makeUser('owner@b.com');
    const other = makeUser('other@b.com');
    const c = createCharacter({ name: '유리', persona: '스물둘 대학생. 소꿉친구이고 무뚝뚝하다.', greeting: '안녕' }, owner.id);
    assert.equal(publicCharacter(c, other).persona, undefined);
    assert.ok(publicCharacter(c, owner).persona);
  });
});

describe('대화 기록 → API 메시지', () => {
  test('첫 줄이 캐릭터 인사면 앞에 시작 신호를 넣는다', () => {
    const out = toApiMessages([{ role: 'assistant', content: '안녕' }], 10);
    assert.equal(out[0].role, 'user');
    assert.equal(out[1].role, 'assistant');
  });

  test('연속된 같은 역할은 하나로 합친다', () => {
    const out = toApiMessages(
      [{ role: 'user', content: '첫째' }, { role: 'user', content: '둘째' }, { role: 'assistant', content: '응' }],
      10
    );
    assert.equal(out.length, 2);
    assert.equal(out[0].content, '첫째\n둘째');
  });

  test('기억할 턴 수를 넘으면 오래된 대화를 버린다', () => {
    const rows = Array.from({ length: 30 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: `m${i}` }));
    assert.equal(toApiMessages(rows, 3).length, 6);
  });
});

describe('결제', () => {
  test('모의 모드에서 구독하면 한 달 이용권이 생긴다', async () => {
    let user = makeUser();
    await registerBillingKey({ user, authKey: 'x' });
    user = getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id);
    await charge({ user, planId: 'lite' });
    const after = getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id);
    assert.equal(after.plan, 'lite');
    assert.ok(new Date(after.plan_expires_at) > new Date());
    assert.equal(getDb().prepare("SELECT COUNT(*) n FROM payments WHERE status='paid'").get().n, 1);
  });

  test('결제수단 없이 결제하면 거절한다', async () => {
    const user = makeUser();
    await assert.rejects(() => charge({ user, planId: 'lite' }), /결제수단/);
  });

  test('남은 기간이 있으면 이어붙인다', () => {
    const user = makeUser();
    const first = new Date(activatePlan(user.id, 'lite'));
    const second = new Date(activatePlan(user.id, 'lite'));
    assert.ok(second > first);
  });

  test('해지 예약한 구독은 자동결제 대상에서 빠진다', async () => {
    let user = makeUser();
    await registerBillingKey({ user, authKey: 'x' });
    user = getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id);
    await charge({ user, planId: 'lite' });
    getDb().prepare('UPDATE users SET plan_expires_at=? WHERE id=?').run(new Date(Date.now() - 1000).toISOString(), user.id);
    cancelAtPeriodEnd(user.id);
    assert.deepEqual(await runRenewals(), []);
  });

  test('만료된 구독은 자동으로 재결제된다', async () => {
    let user = makeUser();
    await registerBillingKey({ user, authKey: 'x' });
    user = getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id);
    await charge({ user, planId: 'lite' });
    getDb().prepare('UPDATE users SET plan_expires_at=? WHERE id=?').run(new Date(Date.now() - 1000).toISOString(), user.id);
    const results = await runRenewals();
    assert.equal(results.length, 1);
    assert.equal(results[0].ok, true);
    assert.ok(new Date(getDb().prepare('SELECT plan_expires_at e FROM users WHERE id=?').get(user.id).e) > new Date());
  });
});

describe('매출 집계', () => {
  test('결제와 원가가 대시보드 숫자에 반영된다', async () => {
    let user = makeUser();
    await registerBillingKey({ user, authKey: 'x' });
    user = getDb().prepare('SELECT * FROM users WHERE id=?').get(user.id);
    await charge({ user, planId: 'lite' });
    recordUsage({ userId: user.id, model: 'claude-sonnet-5', usage: { input_tokens: 100_000, output_tokens: 20_000 } });

    const d = dashboard();
    assert.equal(d.revenueKrw, PLANS.lite.priceKrw);
    assert.equal(d.mrrKrw, PLANS.lite.priceKrw);
    assert.ok(d.costKrw > 0);
    assert.equal(d.marginKrw, d.revenueKrw - d.costKrw);
    assert.equal(d.paidUsers, 1);
    assert.equal(d.goalKrw, 300000);
    assert.ok(d.litePlansNeeded > 0);
  });
});
