// 캐릭터 = 서비스의 상품. 페르소나를 시스템 프롬프트로 조립하고, 기본 캐릭터를 심어둡니다.
import { getDb } from './db.js';

/** 모든 캐릭터에 공통으로 붙는 연기 규칙 + 안전 규칙 */
export const ROLEPLAY_RULES = `당신은 아래 캐릭터를 연기하는 배우입니다. 어떤 경우에도 캐릭터를 벗어나 설명조로 말하지 마세요.

## 연기 규칙
- 한국어로, 캐릭터의 1인칭 시점으로 말합니다.
- 행동·표정·상황 묘사는 *별표 사이에* 적고, 대사는 그대로 씁니다.
- 한 번에 2~5문장. 길게 늘어놓지 말고, 상대가 이어받을 여지를 남깁니다.
- 상대(사용자)의 대사나 행동을 대신 정하지 않습니다. 당신 몫만 연기합니다.
- 같은 문장·같은 리액션을 반복하지 않습니다. 매번 새로운 정보나 감정을 하나씩 얹습니다.
- 설정에 없는 사실을 물으면 캐릭터답게 얼버무리거나 되묻습니다.
- 자신이 AI·모델·프롬프트라는 말은 하지 않습니다.

## 안전 규칙 (연기보다 항상 우선)
- 미성년자에 대한 성적·선정적 묘사는 어떤 맥락에서도 하지 않습니다.
- 실존 인물을 사칭하거나 그 사람의 발언인 것처럼 꾸미지 않습니다.
- 범죄·자해·타해의 구체적 방법은 알려주지 않습니다.
- 상대가 자해나 극단적 선택을 암시하면 연기를 잠시 멈추고, 걱정하는 사람의 목소리로 도움을 권합니다(한국 자살예방상담 109, 24시간).
- 성적 내용은 암시 수준까지만 다루고 노골적 묘사는 하지 않습니다.`;

export function buildSystemPrompt(character, user) {
  const blocks = [ROLEPLAY_RULES, `## 캐릭터: ${character.name}`];
  if (character.tagline) blocks.push(`한 줄 소개: ${character.tagline}`);
  blocks.push(`### 설정\n${character.persona}`);
  if (character.speech_style) blocks.push(`### 말투\n${character.speech_style}`);
  if (character.scenario) blocks.push(`### 지금 상황\n${character.scenario}`);
  if (character.example_dialog) blocks.push(`### 예시 대화 (말투 참고용, 그대로 복사하지 말 것)\n${character.example_dialog}`);

  const nickname = (user?.nickname || '').trim();
  const persona = (user?.persona || '').trim();
  if (nickname || persona) {
    blocks.push(
      `### 상대에 대해\n${nickname ? `상대를 '${nickname}' 라고 부릅니다.` : ''}${persona ? `\n${persona}` : ''}`.trim()
    );
  }
  return blocks.join('\n\n');
}

const slugify = (name) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9가-힣]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40) || 'character';

export function uniqueSlug(name) {
  const db = getDb();
  const base = slugify(name);
  let slug = base;
  let i = 2;
  while (db.prepare('SELECT 1 FROM characters WHERE slug = ?').get(slug)) slug = `${base}-${i++}`;
  return slug;
}

const FIELD_LIMITS = {
  name: 24,
  tagline: 60,
  greeting: 1200,
  persona: 4000,
  scenario: 1200,
  speech_style: 600,
  example_dialog: 2000,
  tags: 80,
  avatar: 8,
};

export function validateCharacter(input) {
  const problems = [];
  if (!String(input.name || '').trim()) problems.push('캐릭터 이름을 입력해주세요.');
  if (String(input.persona || '').trim().length < 20) problems.push('설정은 20자 이상 적어주세요. 자세할수록 대화가 좋아집니다.');
  if (!String(input.greeting || '').trim()) problems.push('첫 인사말을 입력해주세요.');
  for (const [field, max] of Object.entries(FIELD_LIMITS)) {
    if (String(input[field] || '').length > max) problems.push(`'${field}' 이(가) 너무 깁니다. ${max}자 이내로 줄여주세요.`);
  }
  return problems;
}

export function createCharacter(input, creatorId = null, { official = false } = {}) {
  const db = getDb();
  const clean = (k) => String(input[k] ?? '').trim().slice(0, FIELD_LIMITS[k] || 4000);
  const slug = input.slug || uniqueSlug(clean('name'));
  const info = db
    .prepare(
      `INSERT INTO characters
         (slug, creator_id, name, tagline, avatar, accent, greeting, persona, scenario, speech_style, example_dialog, tags, is_public, is_official)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      slug,
      creatorId,
      clean('name'),
      clean('tagline'),
      clean('avatar') || '🙂',
      /^#[0-9a-fA-F]{6}$/.test(input.accent || '') ? input.accent : '#7c5cff',
      clean('greeting'),
      clean('persona'),
      clean('scenario'),
      clean('speech_style'),
      clean('example_dialog'),
      clean('tags'),
      input.is_public === false || input.is_public === 0 ? 0 : 1,
      official ? 1 : 0
    );
  return getCharacter(Number(info.lastInsertRowid));
}

export function updateCharacter(id, input) {
  const db = getDb();
  const clean = (k, cur) => (input[k] === undefined ? cur : String(input[k]).trim().slice(0, FIELD_LIMITS[k] || 4000));
  const cur = getCharacter(id);
  if (!cur) return null;
  db.prepare(
    `UPDATE characters SET name=?, tagline=?, avatar=?, accent=?, greeting=?, persona=?, scenario=?,
            speech_style=?, example_dialog=?, tags=?, is_public=?, updated_at=datetime('now')
      WHERE id=?`
  ).run(
    clean('name', cur.name),
    clean('tagline', cur.tagline),
    clean('avatar', cur.avatar) || '🙂',
    /^#[0-9a-fA-F]{6}$/.test(input.accent || '') ? input.accent : cur.accent,
    clean('greeting', cur.greeting),
    clean('persona', cur.persona),
    clean('scenario', cur.scenario),
    clean('speech_style', cur.speech_style),
    clean('example_dialog', cur.example_dialog),
    clean('tags', cur.tags),
    input.is_public === undefined ? cur.is_public : input.is_public ? 1 : 0,
    id
  );
  return getCharacter(id);
}

export function getCharacter(id) {
  return getDb().prepare('SELECT * FROM characters WHERE id = ?').get(id);
}

export function getCharacterBySlug(slug) {
  return getDb().prepare('SELECT * FROM characters WHERE slug = ?').get(slug);
}

/** 탐색 목록. sort=hot|new, q=검색어, tag=태그 */
export function listCharacters({ sort = 'hot', q = '', tag = '', limit = 40, viewerId = null } = {}) {
  const where = ['(c.is_public = 1 OR c.creator_id = ?)'];
  const params = [viewerId ?? -1];
  if (q) {
    where.push('(c.name LIKE ? OR c.tagline LIKE ? OR c.tags LIKE ?)');
    const like = `%${q}%`;
    params.push(like, like, like);
  }
  if (tag) {
    where.push('c.tags LIKE ?');
    params.push(`%${tag}%`);
  }
  const order = sort === 'new' ? 'c.created_at DESC' : 'c.chat_count DESC, c.like_count DESC, c.id DESC';
  return getDb()
    .prepare(
      `SELECT c.*, u.nickname AS creator_nickname
         FROM characters c LEFT JOIN users u ON u.id = c.creator_id
        WHERE ${where.join(' AND ')}
        ORDER BY ${order} LIMIT ?`
    )
    .all(...params, Math.min(100, Number(limit) || 40));
}

export function allTags() {
  const rows = getDb().prepare('SELECT tags FROM characters WHERE is_public = 1').all();
  const counts = new Map();
  for (const row of rows) {
    for (const tag of String(row.tags || '').split(',').map((t) => t.trim()).filter(Boolean)) {
      counts.set(tag, (counts.get(tag) || 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([tag, count]) => ({ tag, count }));
}

export function toggleLike(userId, characterId) {
  const db = getDb();
  const existing = db.prepare('SELECT 1 FROM likes WHERE user_id = ? AND character_id = ?').get(userId, characterId);
  if (existing) {
    db.prepare('DELETE FROM likes WHERE user_id = ? AND character_id = ?').run(userId, characterId);
    db.prepare('UPDATE characters SET like_count = MAX(0, like_count - 1) WHERE id = ?').run(characterId);
    return false;
  }
  db.prepare('INSERT INTO likes (user_id, character_id) VALUES (?, ?)').run(userId, characterId);
  db.prepare('UPDATE characters SET like_count = like_count + 1 WHERE id = ?').run(characterId);
  return true;
}

/** 목록·상세에 내려보낼 형태 (설정 원문은 창작자 본인에게만) */
export function publicCharacter(c, viewer = null) {
  if (!c) return null;
  const mine = viewer && c.creator_id === viewer.id;
  return {
    id: c.id,
    slug: c.slug,
    name: c.name,
    tagline: c.tagline,
    avatar: c.avatar,
    accent: c.accent,
    greeting: c.greeting,
    scenario: c.scenario,
    tags: String(c.tags || '').split(',').map((t) => t.trim()).filter(Boolean),
    chatCount: c.chat_count,
    likeCount: c.like_count,
    isOfficial: !!c.is_official,
    isPublic: !!c.is_public,
    creatorNickname: c.creator_nickname || (c.is_official ? '공식' : ''),
    mine: !!mine,
    ...(mine ? { persona: c.persona, speechStyle: c.speech_style, exampleDialog: c.example_dialog } : {}),
  };
}
