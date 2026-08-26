// 사용량·한도. 메시지 수가 아니라 "API 원가(원)" 로 막기 때문에 어떤 모델을 쓰든 마진이 먼저 지켜집니다.
import { getDb } from './db.js';
import { getPlan, costKrw } from './config.js';

const KST_OFFSET_MIN = 9 * 60;
const pad = (n) => String(n).padStart(2, '0');
const toSqlUtc = (d) =>
  `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
  `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;

/** 한국 시간 기준 '이번 달'의 시작/끝을 SQLite 가 비교할 수 있는 UTC 문자열로 돌려줍니다. */
export function monthRange(now = new Date()) {
  const kst = new Date(now.getTime() + KST_OFFSET_MIN * 60_000);
  const startKst = Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), 1);
  const endKst = Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth() + 1, 1);
  return {
    start: toSqlUtc(new Date(startKst - KST_OFFSET_MIN * 60_000)),
    end: toSqlUtc(new Date(endKst - KST_OFFSET_MIN * 60_000)),
    label: `${kst.getUTCFullYear()}-${pad(kst.getUTCMonth() + 1)}`,
  };
}

/** 결제 만료일이 지났으면 무료 플랜으로 취급합니다. */
export function effectivePlanId(user) {
  if (!user) return 'free';
  if (user.plan === 'free') return 'free';
  if (!user.plan_expires_at) return 'free';
  return new Date(user.plan_expires_at).getTime() > Date.now() ? user.plan : 'free';
}

export function effectivePlan(user) {
  return getPlan(effectivePlanId(user));
}

export function monthlyUsage(userId, now = new Date()) {
  const { start, end } = monthRange(now);
  const row = getDb()
    .prepare(
      `SELECT COALESCE(SUM(cost_krw), 0) AS cost, COUNT(*) AS requests,
              COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens
         FROM usage_events
        WHERE user_id = ? AND created_at >= ? AND created_at < ?`
    )
    .get(userId, start, end);
  return { costKrw: Number(row.cost) || 0, requests: Number(row.requests) || 0, tokens: Number(row.tokens) || 0 };
}

/** 이번 달에 산 충전팩 합계 */
export function monthlyTopupCap(userId, now = new Date()) {
  const { start, end } = monthRange(now);
  const row = getDb()
    .prepare('SELECT COALESCE(SUM(cap_krw),0) AS cap FROM topups WHERE user_id = ? AND created_at >= ? AND created_at < ?')
    .get(userId, start, end);
  return Number(row.cap) || 0;
}

/** 지금 메시지를 받아줘도 되는지 + 화면에 보여줄 사용량 요약 */
export function quotaStatus(user, now = new Date()) {
  const plan = effectivePlan(user);
  const used = monthlyUsage(user.id, now);
  const topup = monthlyTopupCap(user.id, now);
  const cap = plan.costCapKrw + topup;
  const remaining = Math.max(0, cap - used.costKrw);
  const perMessage = estimatedMessageCost(plan);
  return {
    plan: plan.id,
    planName: plan.name,
    model: plan.model,
    capKrw: cap,
    topupKrw: topup,
    usedKrw: Math.round(used.costKrw * 100) / 100,
    remainingKrw: Math.round(remaining * 100) / 100,
    percent: Math.min(100, Math.round((used.costKrw / cap) * 100)),
    messagesSent: used.requests,
    // 남은 원가로 대략 몇 메시지 더 보낼 수 있는지
    messagesLeft: Math.floor(remaining / perMessage),
    monthlyMessages: Math.floor(cap / perMessage),
    allowed: used.costKrw < cap,
  };
}

/** 메시지 한 건당 예상 원가 — 남은 횟수 안내와 한도 초과 예방에 씁니다. */
export function estimatedMessageCost(plan) {
  return Math.max(
    0.5,
    costKrw({ model: plan.model, inputTokens: 2600, outputTokens: Math.round(plan.maxTokens * 0.6) })
  );
}

export function recordUsage({ userId, conversationId = null, characterId = null, model, usage }) {
  const inputTokens = usage?.input_tokens || 0;
  const outputTokens = usage?.output_tokens || 0;
  const cacheReadTokens = usage?.cache_read_input_tokens || 0;
  const cacheWriteTokens = usage?.cache_creation_input_tokens || 0;
  const cost = costKrw({ model, inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens });
  getDb()
    .prepare(
      `INSERT INTO usage_events
         (user_id, conversation_id, character_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_krw)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(userId, conversationId, characterId, model, inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens, cost);
  return { costKrw: cost, inputTokens, outputTokens };
}
