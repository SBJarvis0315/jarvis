// 계정 · 캐릭터 라우트
import { readJson, sendJson, HttpError } from '../http.js';
import { config, PLANS, TOPUP_PACKS, getPlan } from '../config.js';
import {
  createUser, login, createSession, destroySession, publicUser, validateSignup, findUserByEmail, isAdmin,
} from '../auth.js';
import { getDb } from '../db.js';
import { quotaStatus, effectivePlan } from '../quota.js';
import {
  listCharacters, getCharacterBySlug, getCharacter, createCharacter, updateCharacter,
  validateCharacter, publicCharacter, toggleLike, allTags,
} from '../characters.js';

const requireUser = (ctx) => {
  if (!ctx.user) throw new HttpError(401, '로그인이 필요합니다.');
  return ctx.user;
};

const planSummaries = () =>
  Object.values(PLANS).map(({ id, name, priceKrw, blurb, features, model }) => ({
    id, name, priceKrw, blurb, features, model,
  }));

export function registerCoreRoutes(router) {
  router.post('/api/auth/signup', async (ctx) => {
    const body = await readJson(ctx.req);
    const problems = validateSignup(body);
    if (problems.length) throw new HttpError(400, problems.join(' '));
    if (findUserByEmail(body.email)) throw new HttpError(409, '이미 가입된 이메일입니다.');
    const user = createUser(body);
    ctx.startSession(user.id);
    sendJson(ctx.res, 201, { user: publicUser(user), quota: quotaStatus(user) });
  });

  router.post('/api/auth/login', async (ctx) => {
    const body = await readJson(ctx.req);
    if (!ctx.loginAllowed(ctx.ip)) throw new HttpError(429, '로그인 시도가 너무 잦습니다. 잠시 후 다시 시도해주세요.');
    const user = login(body);
    if (!user) throw new HttpError(401, '이메일 또는 비밀번호가 올바르지 않습니다.');
    ctx.startSession(user.id);
    sendJson(ctx.res, 200, { user: publicUser(user), quota: quotaStatus(user) });
  });

  router.post('/api/auth/logout', async (ctx) => {
    destroySession(ctx.sessionToken);
    ctx.clearSession();
    sendJson(ctx.res, 200, { ok: true });
  });

  router.get('/api/me', async (ctx) => {
    sendJson(ctx.res, 200, {
      user: ctx.user ? publicUser(ctx.user) : null,
      quota: ctx.user ? quotaStatus(ctx.user) : null,
      plans: planSummaries(),
      packs: Object.values(TOPUP_PACKS),
      site: { name: config.siteName, goalKrw: config.goalKrw },
    });
  });

  router.patch('/api/me', async (ctx) => {
    const user = requireUser(ctx);
    const body = await readJson(ctx.req);
    getDb()
      .prepare('UPDATE users SET nickname = ?, persona = ? WHERE id = ?')
      .run(String(body.nickname ?? user.nickname).slice(0, 20), String(body.persona ?? user.persona).slice(0, 600), user.id);
    sendJson(ctx.res, 200, { user: publicUser(ctx.reloadUser()) });
  });

  router.get('/api/characters', async (ctx) => {
    const rows = listCharacters({
      sort: ctx.query.get('sort') || 'hot',
      q: (ctx.query.get('q') || '').slice(0, 40),
      tag: (ctx.query.get('tag') || '').slice(0, 20),
      viewerId: ctx.user?.id ?? null,
    });
    sendJson(ctx.res, 200, {
      characters: rows.map((c) => publicCharacter(c, ctx.user)),
      tags: allTags(),
    });
  });

  router.get('/api/characters/:slug', async (ctx) => {
    const character = getCharacterBySlug(ctx.params.slug);
    if (!character || (!character.is_public && character.creator_id !== ctx.user?.id)) {
      throw new HttpError(404, '캐릭터를 찾을 수 없습니다.');
    }
    sendJson(ctx.res, 200, { character: publicCharacter(character, ctx.user) });
  });

  router.post('/api/characters', async (ctx) => {
    const user = requireUser(ctx);
    const plan = effectivePlan(user);
    if (!plan.canCreate) throw new HttpError(402, '캐릭터 만들기는 라이트 플랜부터 이용할 수 있습니다.');
    const mine = getDb().prepare('SELECT COUNT(*) AS n FROM characters WHERE creator_id = ?').get(user.id).n;
    if (mine >= plan.maxCharacters) throw new HttpError(402, `${plan.name} 플랜에서는 캐릭터를 ${plan.maxCharacters}개까지 만들 수 있습니다.`);

    const body = await readJson(ctx.req);
    const problems = validateCharacter(body);
    if (problems.length) throw new HttpError(400, problems.join(' '));
    const character = createCharacter(body, user.id);
    sendJson(ctx.res, 201, { character: publicCharacter(character, user) });
  });

  router.patch('/api/characters/:slug', async (ctx) => {
    const user = requireUser(ctx);
    const character = getCharacterBySlug(ctx.params.slug);
    if (!character) throw new HttpError(404, '캐릭터를 찾을 수 없습니다.');
    if (character.creator_id !== user.id && !isAdmin(user)) throw new HttpError(403, '내가 만든 캐릭터만 수정할 수 있습니다.');
    const body = await readJson(ctx.req);
    const problems = validateCharacter({ ...character, ...body });
    if (problems.length) throw new HttpError(400, problems.join(' '));
    sendJson(ctx.res, 200, { character: publicCharacter(updateCharacter(character.id, body), user) });
  });

  router.delete('/api/characters/:slug', async (ctx) => {
    const user = requireUser(ctx);
    const character = getCharacterBySlug(ctx.params.slug);
    if (!character) throw new HttpError(404, '캐릭터를 찾을 수 없습니다.');
    if (character.creator_id !== user.id && !isAdmin(user)) throw new HttpError(403, '내가 만든 캐릭터만 지울 수 있습니다.');
    getDb().prepare('DELETE FROM characters WHERE id = ?').run(character.id);
    sendJson(ctx.res, 200, { ok: true });
  });

  router.post('/api/characters/:slug/like', async (ctx) => {
    const user = requireUser(ctx);
    const character = getCharacterBySlug(ctx.params.slug);
    if (!character) throw new HttpError(404, '캐릭터를 찾을 수 없습니다.');
    const liked = toggleLike(user.id, character.id);
    sendJson(ctx.res, 200, { liked, character: publicCharacter(getCharacter(character.id), user) });
  });

  router.get('/api/plans', async (ctx) => {
    sendJson(ctx.res, 200, { plans: planSummaries(), packs: Object.values(TOPUP_PACKS), currentPlan: getPlan(ctx.user?.plan).id });
  });
}
