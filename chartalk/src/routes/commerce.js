// 결제 · 관리자 라우트
import { readJson, sendJson, HttpError } from '../http.js';
import { config, PLANS, TOPUP_PACKS, PAID_PLANS } from '../config.js';
import { publicUser, isAdmin } from '../auth.js';
import { getDb } from '../db.js';
import { quotaStatus } from '../quota.js';
import { registerBillingKey, charge, buyTopup, cancelAtPeriodEnd, resumeSubscription, runRenewals, customerKeyFor } from '../billing.js';
import { dashboard } from '../stats.js';

const requireUser = (ctx) => {
  if (!ctx.user) throw new HttpError(401, '로그인이 필요합니다.');
  return ctx.user;
};

const requireAdmin = (ctx) => {
  const user = requireUser(ctx);
  if (!isAdmin(user)) throw new HttpError(403, '관리자만 볼 수 있습니다.');
  return user;
};

export function registerCommerceRoutes(router) {
  router.get('/api/billing/config', async (ctx) => {
    sendJson(ctx.res, 200, {
      clientKey: config.toss.clientKey,
      mock: config.toss.mock,
      customerKey: ctx.user ? customerKeyFor(ctx.user) : null,
      successUrl: `${config.siteUrl}/billing/success`,
      failUrl: `${config.siteUrl}/billing/fail`,
      plans: Object.values(PLANS).map(({ id, name, priceKrw }) => ({ id, name, priceKrw })),
      packs: Object.values(TOPUP_PACKS),
    });
  });

  // 카드 등록(빌링키 발급) + 원하면 곧바로 구독 결제까지
  router.post('/api/billing/register', async (ctx) => {
    const user = requireUser(ctx);
    const body = await readJson(ctx.req);
    if (!config.toss.mock && !body.authKey) throw new HttpError(400, '카드 인증 정보가 없습니다.');
    await registerBillingKey({ user, authKey: body.authKey, customerKey: body.customerKey });
    const refreshed = ctx.reloadUser();
    if (body.planId && PAID_PLANS.includes(body.planId)) {
      await charge({ user: refreshed, planId: body.planId });
    }
    const final = ctx.reloadUser();
    sendJson(ctx.res, 200, { user: publicUser(final), quota: quotaStatus(final) });
  });

  router.post('/api/billing/subscribe', async (ctx) => {
    const user = requireUser(ctx);
    const body = await readJson(ctx.req);
    if (!PAID_PLANS.includes(body.planId)) throw new HttpError(400, '없는 요금제입니다.');
    if (!user.billing_key) throw new HttpError(402, '결제수단을 먼저 등록해주세요.');
    const result = await charge({ user, planId: body.planId });
    const refreshed = ctx.reloadUser();
    sendJson(ctx.res, 200, { ...result, user: publicUser(refreshed), quota: quotaStatus(refreshed) });
  });

  router.post('/api/billing/topup', async (ctx) => {
    const user = requireUser(ctx);
    const body = await readJson(ctx.req);
    if (!TOPUP_PACKS[body.packId]) throw new HttpError(400, '없는 충전 상품입니다.');
    if (!user.billing_key) throw new HttpError(402, '결제수단을 먼저 등록해주세요.');
    const result = await buyTopup({ user, packId: body.packId });
    sendJson(ctx.res, 200, { ...result, quota: quotaStatus(ctx.reloadUser()) });
  });

  router.post('/api/billing/cancel', async (ctx) => {
    const user = requireUser(ctx);
    cancelAtPeriodEnd(user.id);
    sendJson(ctx.res, 200, { user: publicUser(ctx.reloadUser()) });
  });

  router.post('/api/billing/resume', async (ctx) => {
    const user = requireUser(ctx);
    resumeSubscription(user.id);
    sendJson(ctx.res, 200, { user: publicUser(ctx.reloadUser()) });
  });

  router.get('/api/billing/history', async (ctx) => {
    const user = requireUser(ctx);
    const rows = getDb()
      .prepare('SELECT kind, plan, amount_krw, status, paid_at, created_at FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT 30')
      .all(user.id);
    sendJson(ctx.res, 200, { payments: rows });
  });

  router.get('/api/admin/stats', async (ctx) => {
    requireAdmin(ctx);
    sendJson(ctx.res, 200, dashboard());
  });

  // 정기결제 수동 실행 (평소에는 npm run renew 를 크론에 걸어둡니다)
  router.post('/api/admin/renew', async (ctx) => {
    requireAdmin(ctx);
    sendJson(ctx.res, 200, { results: await runRenewals() });
  });
}
