// 프레임워크 없이 쓰는 작은 HTTP 도구들 (라우팅, JSON, 쿠키, 정적파일, SSE).
import { createReadStream, existsSync, statSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';

export function sendJson(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(body);
}

export function sendError(res, status, message) {
  sendJson(res, status, { error: message });
}

export async function readJson(req, limit = 512 * 1024) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new HttpError(413, '요청이 너무 큽니다.');
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new HttpError(400, 'JSON 형식이 올바르지 않습니다.');
  }
}

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function parseCookies(req) {
  const out = {};
  for (const part of String(req.headers.cookie || '').split(';')) {
    const idx = part.indexOf('=');
    if (idx < 0) continue;
    out[part.slice(0, idx).trim()] = decodeURIComponent(part.slice(idx + 1).trim());
  }
  return out;
}

export function setCookie(res, name, value, { maxAge, secure } = {}) {
  const parts = [`${name}=${encodeURIComponent(value)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax'];
  if (maxAge !== undefined) parts.push(`Max-Age=${maxAge}`);
  if (secure) parts.push('Secure');
  const prev = res.getHeader('Set-Cookie');
  res.setHeader('Set-Cookie', prev ? [].concat(prev, parts.join('; ')) : parts.join('; '));
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json',
};

export function serveStatic(res, root, pathname) {
  const rel = normalize(decodeURIComponent(pathname)).replace(/^(\.\.[/\\])+/, '');
  let file = join(root, rel);
  if (!file.startsWith(root)) return false;
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, 'index.html');
  if (!existsSync(file)) return false;
  res.writeHead(200, {
    'Content-Type': MIME[extname(file)] || 'application/octet-stream',
    'Cache-Control': extname(file) === '.html' ? 'no-cache' : 'public, max-age=3600',
  });
  createReadStream(file).pipe(res);
  return true;
}

/** 아주 작은 라우터: router.get('/api/users/:id', handler) */
export function createRouter() {
  const routes = [];
  const add = (method) => (path, handler) => {
    const names = [];
    const pattern = new RegExp(
      '^' +
        path.replace(/:[A-Za-z0-9_]+/g, (m) => {
          names.push(m.slice(1));
          return '([^/]+)';
        }) +
        '$'
    );
    routes.push({ method, pattern, names, handler });
  };
  return {
    get: add('GET'),
    post: add('POST'),
    put: add('PUT'),
    patch: add('PATCH'),
    delete: add('DELETE'),
    match(method, pathname) {
      for (const route of routes) {
        if (route.method !== method) continue;
        const m = pathname.match(route.pattern);
        if (!m) continue;
        const params = {};
        route.names.forEach((name, i) => (params[name] = decodeURIComponent(m[i + 1])));
        return { handler: route.handler, params };
      }
      return null;
    },
  };
}

/** Server-Sent Events 스트림 시작 */
export function startSse(res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write(': open\n\n');
  return {
    send(event, data) {
      res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    },
    close() {
      res.end();
    },
  };
}

/** 아주 단순한 메모리 기반 요청 제한 */
export function rateLimiter({ windowMs, max }) {
  const hits = new Map();
  return (key) => {
    const now = Date.now();
    const list = (hits.get(key) || []).filter((t) => now - t < windowMs);
    list.push(now);
    hits.set(key, list);
    if (hits.size > 5000) for (const [k, v] of hits) if (!v.some((t) => now - t < windowMs)) hits.delete(k);
    return list.length <= max;
  };
}
