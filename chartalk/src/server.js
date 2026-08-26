import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadEnv, config } from './config.js';

loadEnv();

const { openDb } = await import('./db.js');
const { seedCharacters } = await import('./seed.js');
const { userFromSession, createSession, findUserById } = await import('./auth.js');
const { createRouter, serveStatic, parseCookies, setCookie, sendError, rateLimiter, HttpError } = await import('./http.js');
const { registerCoreRoutes } = await import('./routes/core.js');
const { registerChatRoutes } = await import('./routes/chat.js');
const { registerCommerceRoutes } = await import('./routes/commerce.js');

const here = dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = join(here, '..', 'public');
const SESSION_COOKIE = 'sid';
const secureCookies = process.env.NODE_ENV === 'production';

openDb();
const seeded = seedCharacters();

const router = createRouter();
registerCoreRoutes(router);
registerChatRoutes(router);
registerCommerceRoutes(router);

const loginAllowed = rateLimiter({ windowMs: 5 * 60_000, max: 15 });
const chatAllowed = rateLimiter({ windowMs: 60_000, max: 25 });

// 주소 → 페이지 파일
const PAGES = {
  '/': 'index.html',
  '/chat': 'chat.html',
  '/create': 'create.html',
  '/account': 'account.html',
  '/admin': 'admin.html',
  '/billing/success': 'billing-success.html',
  '/billing/fail': 'billing-fail.html',
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;

  try {
    const cookies = parseCookies(req);
    const sessionToken = cookies[SESSION_COOKIE];
    let user = userFromSession(sessionToken);

    const ctx = {
      req,
      res,
      url,
      query: url.searchParams,
      params: {},
      user,
      sessionToken,
      ip: req.headers['x-forwarded-for']?.split(',')[0].trim() || req.socket.remoteAddress || 'unknown',
      loginAllowed,
      chatAllowed,
      startSession(userId) {
        const { token } = createSession(userId);
        setCookie(res, SESSION_COOKIE, token, { maxAge: 30 * 86400, secure: secureCookies });
        ctx.user = findUserById(userId);
        ctx.sessionToken = token;
      },
      clearSession() {
        setCookie(res, SESSION_COOKIE, '', { maxAge: 0, secure: secureCookies });
        ctx.user = null;
      },
      reloadUser() {
        ctx.user = findUserById(ctx.user.id);
        return ctx.user;
      },
    };

    const route = router.match(req.method, pathname);
    if (route) {
      // 쿠키 기반 API 이므로 다른 사이트에서 온 상태변경 요청은 막습니다.
      if (req.method !== 'GET' && !sameOrigin(req, url)) throw new HttpError(403, '요청 출처를 확인할 수 없습니다.');
      ctx.params = route.params;
      await route.handler(ctx);
      return;
    }

    if (req.method === 'GET') {
      const page = PAGES[pathname] || (pathname.startsWith('/c/') ? 'chat.html' : null);
      if (page && serveStatic(res, PUBLIC_DIR, `/${page}`)) return;
      if (serveStatic(res, PUBLIC_DIR, pathname)) return;
    }

    if (pathname.startsWith('/api/')) return sendError(res, 404, '없는 API 입니다.');
    res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<meta charset="utf-8"><h1>404</h1><p>페이지를 찾을 수 없습니다. <a href="/">홈으로</a></p>');
  } catch (err) {
    if (res.headersSent) return res.end();
    const status = err instanceof HttpError ? err.status : 500;
    if (status >= 500) console.error('[server]', err);
    sendError(res, status, status >= 500 ? '서버에서 문제가 발생했습니다.' : err.message);
  }
});

function sameOrigin(req, url) {
  const origin = req.headers.origin;
  if (!origin) return true; // 폼/직접 호출이 아닌 서버 간 요청
  try {
    return new URL(origin).host === url.host;
  } catch {
    return false;
  }
}

server.listen(config.port, () => {
  console.log(`\n  ${config.siteName} 실행 중 → ${config.siteUrl}`);
  if (seeded) console.log(`  공식 캐릭터 ${seeded}명을 준비했습니다.`);
  if (!config.anthropicApiKey) console.log('  ⚠ ANTHROPIC_API_KEY 가 없어 데모 모드로 동작합니다.');
  if (config.toss.mock) console.log('  ⚠ TOSS_SECRET_KEY 가 없어 결제는 모의 모드로 동작합니다.');
  console.log('');
});

export { server };
