// 대화 라우트. 답변은 SSE 로 한 글자씩 흘려보냅니다.
import { readJson, sendJson, HttpError, startSse } from '../http.js';
import { getDb } from '../db.js';
import { effectivePlan, quotaStatus, recordUsage } from '../quota.js';
import { getCharacterBySlug, getCharacter, buildSystemPrompt } from '../characters.js';
import { streamAnswer } from '../claude.js';

const MAX_MESSAGE_LEN = 2000;

const requireUser = (ctx) => {
  if (!ctx.user) throw new HttpError(401, '로그인이 필요합니다.');
  return ctx.user;
};

function ownedConversation(user, id) {
  const row = getDb()
    .prepare(
      `SELECT c.*, ch.name AS character_name, ch.avatar, ch.accent, ch.slug AS character_slug
         FROM conversations c JOIN characters ch ON ch.id = c.character_id
        WHERE c.id = ? AND c.user_id = ?`
    )
    .get(Number(id), user.id);
  if (!row) throw new HttpError(404, '대화를 찾을 수 없습니다.');
  return row;
}

function messagesOf(conversationId) {
  return getDb()
    .prepare('SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id')
    .all(conversationId);
}

/**
 * DB 기록 → Claude 에 보낼 messages 배열.
 * 첫 줄이 캐릭터 인사면 앞에 대화 시작 신호를 넣고, 연속된 같은 역할은 합칩니다.
 */
export function toApiMessages(rows, historyTurns) {
  const trimmed = rows.slice(-historyTurns * 2);
  const out = [];
  for (const row of trimmed) {
    const role = row.role === 'assistant' ? 'assistant' : 'user';
    const last = out[out.length - 1];
    if (last && last.role === role) last.content += `\n${row.content}`;
    else out.push({ role, content: row.content });
  }
  if (out.length && out[0].role === 'assistant') out.unshift({ role: 'user', content: '(대화를 시작한다)' });
  return out;
}

export function registerChatRoutes(router) {
  router.get('/api/conversations', async (ctx) => {
    const user = requireUser(ctx);
    const rows = getDb()
      .prepare(
        `SELECT c.id, c.title, c.updated_at, ch.name AS character_name, ch.avatar, ch.accent, ch.slug AS character_slug,
                (SELECT content FROM messages m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_message
           FROM conversations c JOIN characters ch ON ch.id = c.character_id
          WHERE c.user_id = ? ORDER BY c.updated_at DESC LIMIT 100`
      )
      .all(user.id);
    sendJson(ctx.res, 200, { conversations: rows });
  });

  router.post('/api/conversations', async (ctx) => {
    const user = requireUser(ctx);
    const body = await readJson(ctx.req);
    const character = getCharacterBySlug(String(body.characterSlug || ''));
    if (!character || (!character.is_public && character.creator_id !== user.id)) {
      throw new HttpError(404, '캐릭터를 찾을 수 없습니다.');
    }
    const plan = effectivePlan(user);
    const db = getDb();
    const open = db.prepare('SELECT COUNT(*) AS n FROM conversations WHERE user_id = ?').get(user.id).n;
    if (open >= plan.maxConversations) {
      throw new HttpError(402, `${plan.name} 플랜에서는 대화방을 ${plan.maxConversations}개까지 둘 수 있습니다. 예전 대화를 지우거나 플랜을 올려주세요.`);
    }

    const info = db
      .prepare('INSERT INTO conversations (user_id, character_id, title) VALUES (?, ?, ?)')
      .run(user.id, character.id, character.name);
    const conversationId = Number(info.lastInsertRowid);
    db.prepare("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'assistant', ?)")
      .run(conversationId, character.greeting);
    db.prepare('UPDATE characters SET chat_count = chat_count + 1 WHERE id = ?').run(character.id);

    sendJson(ctx.res, 201, {
      conversation: ownedConversation(user, conversationId),
      messages: messagesOf(conversationId),
    });
  });

  router.get('/api/conversations/:id', async (ctx) => {
    const user = requireUser(ctx);
    const conversation = ownedConversation(user, ctx.params.id);
    sendJson(ctx.res, 200, { conversation, messages: messagesOf(conversation.id) });
  });

  router.delete('/api/conversations/:id', async (ctx) => {
    const user = requireUser(ctx);
    const conversation = ownedConversation(user, ctx.params.id);
    getDb().prepare('DELETE FROM conversations WHERE id = ?').run(conversation.id);
    sendJson(ctx.res, 200, { ok: true });
  });

  // 메시지 보내기 (SSE 응답)
  router.post('/api/conversations/:id/messages', async (ctx) => {
    const user = requireUser(ctx);
    const conversation = ownedConversation(user, ctx.params.id);
    const body = await readJson(ctx.req);
    const text = String(body.message || '').trim().slice(0, MAX_MESSAGE_LEN);
    if (!text) throw new HttpError(400, '보낼 내용을 입력해주세요.');
    if (!ctx.chatAllowed(`u${user.id}`)) throw new HttpError(429, '너무 빠르게 보내고 있어요. 잠시 후 다시 시도해주세요.');

    const quota = quotaStatus(user);
    if (!quota.allowed) throw new HttpError(402, '이번 달 메시지를 모두 사용했습니다. 충전하거나 플랜을 올리면 바로 이어서 대화할 수 있어요.');

    getDb().prepare("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)").run(conversation.id, text);
    await streamReply(ctx, user, conversation);
  });

  // 마지막 답변이 마음에 안 들 때 다시 생성
  router.post('/api/conversations/:id/regenerate', async (ctx) => {
    const user = requireUser(ctx);
    const conversation = ownedConversation(user, ctx.params.id);
    if (!ctx.chatAllowed(`u${user.id}`)) throw new HttpError(429, '너무 빠르게 보내고 있어요. 잠시 후 다시 시도해주세요.');
    const quota = quotaStatus(user);
    if (!quota.allowed) throw new HttpError(402, '이번 달 메시지를 모두 사용했습니다.');

    const db = getDb();
    const rows = messagesOf(conversation.id);
    const last = rows[rows.length - 1];
    if (!last || last.role !== 'assistant' || rows.length < 3) throw new HttpError(400, '다시 생성할 답변이 없습니다.');
    db.prepare('DELETE FROM messages WHERE id = ?').run(last.id);
    await streamReply(ctx, user, conversation);
  });
}

async function streamReply(ctx, user, conversation) {
  const db = getDb();
  const plan = effectivePlan(user);
  const character = getCharacter(conversation.character_id);
  const system = buildSystemPrompt(character, user);
  const apiMessages = toApiMessages(messagesOf(conversation.id), plan.historyTurns);

  const sse = startSse(ctx.res);
  let answer = '';
  try {
    const result = await streamAnswer({
      model: plan.model,
      maxTokens: plan.maxTokens,
      system,
      messages: apiMessages,
      onText: (chunk) => {
        answer += chunk;
        sse.send('delta', { text: chunk });
      },
    });

    if (result.stopReason === 'refusal' && !answer) {
      sse.send('error', { message: '이 요청은 캐릭터가 이어갈 수 없는 내용이라 답하지 못했어요. 다른 방향으로 말을 걸어보세요.' });
      sse.close();
      return;
    }

    db.prepare("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'assistant', ?)").run(conversation.id, answer);
    db.prepare("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?").run(conversation.id);
    recordUsage({
      userId: user.id,
      conversationId: conversation.id,
      characterId: character.id,
      model: plan.model,
      usage: result.usage,
    });

    sse.send('done', { quota: quotaStatus(user), demo: !!result.demo });
  } catch (err) {
    // 답변이 일부라도 나왔으면 버리지 않고 저장합니다.
    if (answer) {
      db.prepare("INSERT INTO messages (conversation_id, role, content) VALUES (?, 'assistant', ?)").run(conversation.id, answer);
    }
    console.error('[chat] 스트리밍 실패:', err?.status || '', err?.message || err);
    sse.send('error', { message: friendlyError(err) });
  } finally {
    sse.close();
  }
}

function friendlyError(err) {
  const status = err?.status ?? err?.response?.status;
  if (status === 429) return '지금 이용자가 많아 잠시 밀렸어요. 10초 뒤에 다시 보내주세요.';
  if (status === 401 || status === 403) return '서버의 API 키 설정에 문제가 있습니다. 관리자에게 알려주세요.';
  if (status >= 500) return 'AI 서버가 잠시 불안정합니다. 다시 시도해주세요.';
  return '답변을 받지 못했습니다. 다시 시도해주세요.';
}
