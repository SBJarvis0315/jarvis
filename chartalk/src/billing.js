// 토스페이먼츠 자동결제(빌링키) 연동.
// TOSS_SECRET_KEY 가 없으면 모의 모드로 돌아가 결제 흐름 전체를 로컬에서 확인할 수 있습니다.
import { randomBytes } from 'node:crypto';
import { getDb } from './db.js';
import { config, getPlan, PAID_PLANS, TOPUP_PACKS } from './config.js';

const TOSS_API = 'https://api.tosspayments.com/v1';

const authHeader = () => 'Basic ' + Buffer.from(`${config.toss.secretKey}:`).toString('base64');

export function newOrderId(userId) {
  return `cf_${userId}_${Date.now()}_${randomBytes(4).toString('hex')}`;
}

export function customerKeyFor(user) {
  return user.customer_key || `cf_cus_${user.id}_${randomBytes(6).toString('hex')}`;
}

async function tossPost(path, body) {
  const res = await fetch(`${TOSS_API}${path}`, {
    method: 'POST',
    headers: { Authorization: authHeader(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.message || '결제 요청이 거절되었습니다.');
    err.code = data.code || `HTTP_${res.status}`;
    throw err;
  }
  return data;
}

/** 카드 등록(authKey) → 빌링키 발급 후 사용자에게 저장 */
export async function registerBillingKey({ user, authKey, customerKey }) {
  const key = customerKey || customerKeyFor(user);
  let billingKey;
  let cardLabel;

  if (config.toss.mock) {
    billingKey = `mock_bk_${randomBytes(8).toString('hex')}`;
    cardLabel = '테스트카드 ****4321';
  } else {
    const data = await tossPost('/billing/authorizations/issue', { authKey, customerKey: key });
    billingKey = data.billingKey;
    cardLabel = [data.card?.issuerCode, data.card?.number].filter(Boolean).join(' ') || '등록된 카드';
  }

  getDb()
    .prepare('UPDATE users SET billing_key = ?, customer_key = ?, card_label = ? WHERE id = ?')
    .run(billingKey, key, cardLabel, user.id);
  return { billingKey, customerKey: key, cardLabel };
}

/** 등록된 빌링키로 한 달치를 결제합니다. */
export async function charge({ user, planId }) {
  const plan = getPlan(planId);
  if (!PAID_PLANS.includes(plan.id)) throw new Error('결제할 수 있는 요금제가 아닙니다.');
  if (!user.billing_key) throw new Error('등록된 결제수단이 없습니다.');

  const db = getDb();
  const orderId = newOrderId(user.id);
  const orderName = `${config.siteName} ${plan.name} 1개월`;
  db.prepare("INSERT INTO payments (user_id, kind, plan, amount_krw, status, order_id) VALUES (?, 'subscription', ?, ?, ?, ?)")
    .run(user.id, plan.id, plan.priceKrw, 'pending', orderId);

  try {
    let paymentKey;
    if (config.toss.mock) {
      paymentKey = `mock_pk_${randomBytes(8).toString('hex')}`;
    } else {
      const data = await tossPost(`/billing/${user.billing_key}`, {
        customerKey: user.customer_key,
        amount: plan.priceKrw,
        orderId,
        orderName,
        customerEmail: user.email,
      });
      paymentKey = data.paymentKey;
    }
    db.prepare(`UPDATE payments SET status='paid', payment_key=?, paid_at=datetime('now') WHERE order_id=?`)
      .run(paymentKey, orderId);
    activatePlan(user.id, plan.id);
    return { ok: true, orderId, amountKrw: plan.priceKrw };
  } catch (err) {
    db.prepare(`UPDATE payments SET status='failed', fail_reason=? WHERE order_id=?`)
      .run(String(err.code || err.message).slice(0, 200), orderId);
    throw err;
  }
}

/** 충전팩 구매: 등록된 카드로 즉시 결제하고 이번 달 한도를 늘립니다. */
export async function buyTopup({ user, packId }) {
  const pack = TOPUP_PACKS[packId];
  if (!pack) throw new Error('없는 충전 상품입니다.');
  if (!user.billing_key) throw new Error('등록된 결제수단이 없습니다.');

  const db = getDb();
  const orderId = newOrderId(user.id);
  db.prepare("INSERT INTO payments (user_id, kind, plan, amount_krw, status, order_id) VALUES (?, 'topup', ?, ?, ?, ?)")
    .run(user.id, pack.id, pack.amountKrw, 'pending', orderId);

  try {
    let paymentKey;
    if (config.toss.mock) {
      paymentKey = `mock_pk_${randomBytes(8).toString('hex')}`;
    } else {
      const data = await tossPost(`/billing/${user.billing_key}`, {
        customerKey: user.customer_key,
        amount: pack.amountKrw,
        orderId,
        orderName: `${config.siteName} ${pack.name}`,
        customerEmail: user.email,
      });
      paymentKey = data.paymentKey;
    }
    db.prepare("UPDATE payments SET status='paid', payment_key=?, paid_at=datetime('now') WHERE order_id=?")
      .run(paymentKey, orderId);
    db.prepare('INSERT INTO topups (user_id, pack, cap_krw, amount_krw, order_id) VALUES (?, ?, ?, ?, ?)')
      .run(user.id, pack.id, pack.capKrw, pack.amountKrw, orderId);
    return { ok: true, orderId, amountKrw: pack.amountKrw, capKrw: pack.capKrw };
  } catch (err) {
    db.prepare("UPDATE payments SET status='failed', fail_reason=? WHERE order_id=?")
      .run(String(err.code || err.message).slice(0, 200), orderId);
    throw err;
  }
}

/** 결제 성공 시 이용기간을 한 달 연장합니다(남은 기간이 있으면 이어붙임). */
export function activatePlan(userId, planId, now = new Date()) {
  const db = getDb();
  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(userId);
  const current = user?.plan_expires_at ? new Date(user.plan_expires_at) : null;
  const base = current && current.getTime() > now.getTime() && user.plan === planId ? current : now;
  const expires = new Date(base.getTime());
  expires.setMonth(expires.getMonth() + 1);
  db.prepare(
    `UPDATE users SET plan = ?, plan_started_at = COALESCE(plan_started_at, ?), plan_expires_at = ?, cancel_at_period_end = 0
      WHERE id = ?`
  ).run(planId, now.toISOString(), expires.toISOString(), userId);
  return expires.toISOString();
}

/** 해지 예약: 이번 기간까지는 그대로 쓰고 다음 달부터 결제하지 않습니다. */
export function cancelAtPeriodEnd(userId) {
  getDb().prepare('UPDATE users SET cancel_at_period_end = 1 WHERE id = ?').run(userId);
}

export function resumeSubscription(userId) {
  getDb().prepare('UPDATE users SET cancel_at_period_end = 0 WHERE id = ?').run(userId);
}

/** 만료가 임박했거나 지난 구독을 찾아 자동결제합니다. (npm run renew / 크론) */
export async function runRenewals({ now = new Date(), graceHours = 24 } = {}) {
  const db = getDb();
  const due = db
    .prepare(
      `SELECT * FROM users
        WHERE plan != 'free' AND cancel_at_period_end = 0 AND billing_key IS NOT NULL
          AND plan_expires_at IS NOT NULL AND plan_expires_at <= ?`
    )
    .all(new Date(now.getTime() + graceHours * 3600_000).toISOString());

  const results = [];
  for (const user of due) {
    try {
      const res = await charge({ user, planId: user.plan });
      results.push({ userId: user.id, email: user.email, ok: true, amountKrw: res.amountKrw });
    } catch (err) {
      // 결제 실패는 즉시 해지하지 않고 무료로 내립니다(카드 교체 후 재구독 가능).
      if (new Date(user.plan_expires_at).getTime() < now.getTime()) {
        db.prepare(`UPDATE users SET plan = 'free' WHERE id = ?`).run(user.id);
      }
      results.push({ userId: user.id, email: user.email, ok: false, error: String(err.code || err.message) });
    }
  }
  return results;
}
