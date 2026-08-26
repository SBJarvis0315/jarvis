// 회원 가입/로그인/세션. 비밀번호는 scrypt 로 해시하고, 세션은 DB 에 저장합니다.
import { randomBytes, scryptSync, timingSafeEqual, createHash } from 'node:crypto';
import { getDb } from './db.js';
import { config } from './config.js';

const SESSION_DAYS = 30;

export function hashPassword(password) {
  const salt = randomBytes(16).toString('hex');
  const hash = scryptSync(password, salt, 64).toString('hex');
  return `scrypt$${salt}$${hash}`;
}

export function verifyPassword(password, stored) {
  const [scheme, salt, hash] = String(stored || '').split('$');
  if (scheme !== 'scrypt' || !salt || !hash) return false;
  const candidate = scryptSync(password, salt, 64);
  const expected = Buffer.from(hash, 'hex');
  if (candidate.length !== expected.length) return false;
  return timingSafeEqual(candidate, expected);
}

export function validateSignup({ email, password }) {
  const problems = [];
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email || ''))) problems.push('이메일 형식이 올바르지 않습니다.');
  if (String(password || '').length < 8) problems.push('비밀번호는 8자 이상이어야 합니다.');
  return problems;
}

export function createUser({ email, password, nickname = '' }) {
  const db = getDb();
  const normalized = String(email).trim().toLowerCase();
  const exists = db.prepare('SELECT id FROM users WHERE email = ?').get(normalized);
  if (exists) throw new Error('이미 가입된 이메일입니다.');
  const info = db
    .prepare('INSERT INTO users (email, password_hash, nickname) VALUES (?, ?, ?)')
    .run(normalized, hashPassword(password), String(nickname).slice(0, 20) || normalized.split('@')[0]);
  return findUserById(Number(info.lastInsertRowid));
}

export function findUserByEmail(email) {
  return getDb().prepare('SELECT * FROM users WHERE email = ?').get(String(email).trim().toLowerCase());
}

export function findUserById(id) {
  return getDb().prepare('SELECT * FROM users WHERE id = ?').get(id);
}

export function login({ email, password }) {
  const user = findUserByEmail(email);
  if (!user || !verifyPassword(password, user.password_hash)) return null;
  return user;
}

export function createSession(userId) {
  const token = randomBytes(32).toString('hex');
  const expires = new Date(Date.now() + SESSION_DAYS * 86400_000).toISOString();
  getDb().prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)').run(token, userId, expires);
  return { token, expiresAt: expires };
}

export function userFromSession(token) {
  if (!token) return null;
  const row = getDb()
    .prepare(
      `SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
       WHERE s.token = ? AND s.expires_at > datetime('now')`
    )
    .get(token);
  return row || null;
}

export function destroySession(token) {
  if (token) getDb().prepare('DELETE FROM sessions WHERE token = ?').run(token);
}

export function isAdmin(user) {
  if (!user) return false;
  if (config.adminEmails.length) return config.adminEmails.includes(user.email);
  // 관리자 지정이 없으면 1번 계정(= 사이트 주인)이 관리자입니다.
  return user.id === 1;
}

/** 클라이언트에 내려보내도 되는 사용자 정보만 추립니다. */
export function publicUser(user) {
  if (!user) return null;
  return {
    id: user.id,
    email: user.email,
    nickname: user.nickname,
    persona: user.persona,
    plan: user.plan,
    planExpiresAt: user.plan_expires_at,
    cancelAtPeriodEnd: !!user.cancel_at_period_end,
    hasBillingKey: !!user.billing_key,
    cardLabel: user.card_label || '',
    isAdmin: isAdmin(user),
    avatarSeed: createHash('md5').update(user.email).digest('hex').slice(0, 6),
  };
}
