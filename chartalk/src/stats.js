// 관리자 대시보드용 집계. "이번 달 30만원" 목표 대비 어디까지 왔는지 한 화면에서 봅니다.
import { getDb } from './db.js';
import { config, PLANS } from './config.js';
import { monthRange } from './quota.js';

export function dashboard(now = new Date()) {
  const db = getDb();
  const { start, end, label } = monthRange(now);

  const revenue = db
    .prepare(`SELECT COALESCE(SUM(amount_krw),0) AS krw, COUNT(*) AS count
                FROM payments WHERE status='paid' AND paid_at >= ? AND paid_at < ?`)
    .get(start, end);

  const cost = db
    .prepare(`SELECT COALESCE(SUM(cost_krw),0) AS krw, COUNT(*) AS requests
                FROM usage_events WHERE created_at >= ? AND created_at < ?`)
    .get(start, end);

  const subs = db
    .prepare(`SELECT plan, COUNT(*) AS n FROM users
               WHERE plan != 'free' AND plan_expires_at > datetime('now') GROUP BY plan`)
    .all();

  const subsByPlan = Object.fromEntries(subs.map((r) => [r.plan, r.n]));
  const mrr = Object.entries(subsByPlan).reduce((sum, [plan, n]) => sum + (PLANS[plan]?.priceKrw || 0) * n, 0);

  const users = db.prepare('SELECT COUNT(*) AS n FROM users').get().n;
  const newUsers = db.prepare('SELECT COUNT(*) AS n FROM users WHERE created_at >= ? AND created_at < ?').get(start, end).n;
  const activeUsers = db
    .prepare(`SELECT COUNT(DISTINCT user_id) AS n FROM usage_events WHERE created_at >= ? AND created_at < ?`)
    .get(start, end).n;
  const paidUsers = Object.values(subsByPlan).reduce((a, b) => a + b, 0);

  const revenueKrw = Math.round(revenue.krw);
  const costKrw = Math.round(cost.krw);

  return {
    month: label,
    goalKrw: config.goalKrw,
    revenueKrw,
    progressPercent: Math.round((revenueKrw / config.goalKrw) * 100),
    shortfallKrw: Math.max(0, config.goalKrw - revenueKrw),
    // 목표까지 라이트 플랜 몇 명이 더 필요한지
    litePlansNeeded: Math.ceil(Math.max(0, config.goalKrw - mrr) / (PLANS.lite.priceKrw || 1)),
    mrrKrw: mrr,
    costKrw,
    marginKrw: revenueKrw - costKrw,
    marginPercent: revenueKrw ? Math.round(((revenueKrw - costKrw) / revenueKrw) * 100) : 0,
    payments: revenue.count,
    requests: cost.requests,
    users,
    newUsers,
    activeUsers,
    paidUsers,
    conversionPercent: users ? Math.round((paidUsers / users) * 100) : 0,
    subsByPlan,
    daily: dailySeries(now),
    topSpenders: topSpenders(start, end),
    recentPayments: db
      .prepare(`SELECT p.order_id, p.plan, p.amount_krw, p.status, p.paid_at, p.fail_reason, u.email
                  FROM payments p JOIN users u ON u.id = p.user_id
                 ORDER BY p.id DESC LIMIT 12`)
      .all(),
  };
}

/** 최근 30일 매출/원가 추이 */
function dailySeries(now, days = 30) {
  const db = getDb();
  const since = new Date(now.getTime() - days * 86400_000).toISOString().slice(0, 10);
  const rev = db
    .prepare(`SELECT substr(paid_at,1,10) AS day, SUM(amount_krw) AS krw
                FROM payments WHERE status='paid' AND paid_at >= ? GROUP BY day`)
    .all(since);
  const cost = db
    .prepare(`SELECT substr(created_at,1,10) AS day, SUM(cost_krw) AS krw
                FROM usage_events WHERE created_at >= ? GROUP BY day`)
    .all(since);
  const revMap = new Map(rev.map((r) => [r.day, Math.round(r.krw)]));
  const costMap = new Map(cost.map((r) => [r.day, Math.round(r.krw)]));
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const day = new Date(now.getTime() - i * 86400_000).toISOString().slice(0, 10);
    out.push({ day, revenueKrw: revMap.get(day) || 0, costKrw: costMap.get(day) || 0 });
  }
  return out;
}

/** 원가를 많이 쓰는 사용자 — 한도 설계가 맞는지 점검할 때 봅니다. */
function topSpenders(start, end) {
  return getDb()
    .prepare(
      `SELECT u.email, u.plan, COUNT(e.id) AS requests, ROUND(SUM(e.cost_krw)) AS cost_krw
         FROM usage_events e JOIN users u ON u.id = e.user_id
        WHERE e.created_at >= ? AND e.created_at < ?
        GROUP BY u.id ORDER BY SUM(e.cost_krw) DESC LIMIT 8`
    )
    .all(start, end);
}
