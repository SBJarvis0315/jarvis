// SQLite 저장소. Node 22 내장 node:sqlite 를 써서 네이티브 빌드 의존성이 없습니다.
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { config } from './config.js';

let db;

export function openDb(path = config.dbPath) {
  if (db) return db;
  if (path !== ':memory:') mkdirSync(dirname(path), { recursive: true });
  db = new DatabaseSync(path);
  db.exec('PRAGMA journal_mode = WAL');
  db.exec('PRAGMA foreign_keys = ON');
  migrate(db);
  return db;
}

export function getDb() {
  return db || openDb();
}

/** 테스트에서 매번 깨끗한 인메모리 DB 를 쓰기 위한 헬퍼 */
export function resetDbForTest() {
  db = new DatabaseSync(':memory:');
  db.exec('PRAGMA foreign_keys = ON');
  migrate(db);
  return db;
}

function migrate(conn) {
  conn.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      nickname TEXT NOT NULL DEFAULT '',
      persona TEXT NOT NULL DEFAULT '',
      plan TEXT NOT NULL DEFAULT 'free',
      plan_started_at TEXT,
      plan_expires_at TEXT,
      billing_key TEXT,
      customer_key TEXT,
      card_label TEXT,
      cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sessions (
      token TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- 캐릭터: 서비스의 핵심 콘텐츠. 공식 캐릭터 + 유저가 만든 캐릭터가 함께 삽니다.
    CREATE TABLE IF NOT EXISTS characters (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      slug TEXT NOT NULL UNIQUE,
      creator_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
      name TEXT NOT NULL,
      tagline TEXT NOT NULL DEFAULT '',
      avatar TEXT NOT NULL DEFAULT '🙂',
      accent TEXT NOT NULL DEFAULT '#7c5cff',
      greeting TEXT NOT NULL,
      persona TEXT NOT NULL,
      scenario TEXT NOT NULL DEFAULT '',
      speech_style TEXT NOT NULL DEFAULT '',
      example_dialog TEXT NOT NULL DEFAULT '',
      tags TEXT NOT NULL DEFAULT '',
      is_public INTEGER NOT NULL DEFAULT 1,
      is_official INTEGER NOT NULL DEFAULT 0,
      chat_count INTEGER NOT NULL DEFAULT 0,
      like_count INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS likes (
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      PRIMARY KEY (user_id, character_id)
    );

    CREATE TABLE IF NOT EXISTS conversations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
      title TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS usage_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      conversation_id INTEGER,
      character_id INTEGER,
      model TEXT NOT NULL,
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      cache_read_tokens INTEGER NOT NULL DEFAULT 0,
      cache_write_tokens INTEGER NOT NULL DEFAULT 0,
      cost_krw REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS payments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind TEXT NOT NULL DEFAULT 'subscription',
      plan TEXT NOT NULL,
      amount_krw INTEGER NOT NULL,
      status TEXT NOT NULL,
      provider TEXT NOT NULL DEFAULT 'toss',
      order_id TEXT NOT NULL UNIQUE,
      payment_key TEXT,
      fail_reason TEXT,
      paid_at TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- 충전(추가 메시지 팩): 이번 달 사용 한도를 늘려줍니다.
    CREATE TABLE IF NOT EXISTS topups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      pack TEXT NOT NULL,
      cap_krw INTEGER NOT NULL,
      amount_krw INTEGER NOT NULL,
      order_id TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_events(user_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);
    CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at);
    CREATE INDEX IF NOT EXISTS idx_char_public ON characters(is_public, chat_count);
    CREATE INDEX IF NOT EXISTS idx_pay_time ON payments(status, paid_at);
    CREATE INDEX IF NOT EXISTS idx_topup_user ON topups(user_id, created_at);
  `);
}
