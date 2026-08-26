// 서비스 전역 설정. 값은 모두 환경변수로 덮어쓸 수 있게 두었습니다.
import { readFileSync, existsSync } from 'node:fs';

// .env 를 별도 패키지 없이 읽어 process.env 에 채웁니다(이미 있는 값은 유지).
export function loadEnv(path = '.env') {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    const value = m[2].replace(/^["']|["']$/g, '');
    if (process.env[m[1]] === undefined) process.env[m[1]] = value;
  }
}

const num = (key, fallback) => {
  const raw = process.env[key];
  const parsed = raw === undefined ? NaN : Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const config = {
  port: num('PORT', 3000),
  dbPath: process.env.DB_PATH || 'data/chartalk.db',
  siteName: process.env.SITE_NAME || '캐릭터톡',
  siteUrl: process.env.SITE_URL || `http://localhost:${num('PORT', 3000)}`,
  // 관리자 대시보드를 볼 수 있는 이메일 (쉼표 구분)
  adminEmails: (process.env.ADMIN_EMAILS || '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean),
  // 원가를 원화로 환산할 때 쓰는 환율
  usdKrw: num('USD_KRW', 1380),
  // 월 매출 목표 (관리자 대시보드 달성률 기준)
  goalKrw: num('MONTHLY_GOAL_KRW', 300000),
  anthropicApiKey: process.env.ANTHROPIC_API_KEY || '',
  toss: {
    secretKey: process.env.TOSS_SECRET_KEY || '',
    clientKey: process.env.TOSS_CLIENT_KEY || '',
    // 시크릿 키가 없으면 결제를 흉내내는 모의 모드로 돕니다(로컬 개발용).
    get mock() {
      return !process.env.TOSS_SECRET_KEY;
    },
  },
};

// Anthropic 공식 요금표 (USD / 100만 토큰). 원가 계산에만 씁니다.
export const MODEL_PRICING = {
  'claude-opus-5': { input: 5, output: 25 },
  'claude-sonnet-5': { input: 2, output: 10 },
  'claude-haiku-4-5': { input: 1, output: 5 },
};

// effort 옵션을 받아주는 모델 (Haiku 4.5 는 400 을 냅니다)
export const EFFORT_MODELS = new Set(['claude-opus-5', 'claude-sonnet-5']);

const planModel = (key, fallback) => {
  const wanted = process.env[key] || fallback;
  return MODEL_PRICING[wanted] ? wanted : fallback;
};

/**
 * 요금제.
 * costCapKrw = 그 플랜 사용자가 한 달에 태울 수 있는 "API 원가" 상한(원).
 * 메시지 수가 아니라 원가로 막기 때문에, 어떤 모델을 쓰든 마진이 먼저 보장됩니다.
 * 모델은 MODEL_FREE / MODEL_LITE / MODEL_PRO 환경변수로 바꿀 수 있습니다.
 */
export const PLANS = {
  free: {
    id: 'free',
    name: '무료',
    priceKrw: 0,
    costCapKrw: num('FREE_COST_CAP_KRW', 500),
    model: planModel('MODEL_FREE', 'claude-haiku-4-5'),
    maxTokens: 500,
    historyTurns: 12,
    blurb: '가입만 하면 바로 캐릭터와 대화',
    features: ['공식 캐릭터 전체 개방', '월 80메시지 안팎', '대화 1개 보관'],
    maxConversations: 3,
    canCreate: false,
  },
  lite: {
    id: 'lite',
    name: '라이트',
    priceKrw: num('LITE_PRICE_KRW', 9900),
    costCapKrw: num('LITE_COST_CAP_KRW', 3000),
    model: planModel('MODEL_LITE', 'claude-sonnet-5'),
    maxTokens: 700,
    historyTurns: 24,
    blurb: '매일 한두 시간 대화하는 분께',
    features: ['월 200메시지 안팎', '기억하는 대화 길이 2배', '내 캐릭터 5개 제작', '대화 무제한 보관'],
    maxConversations: 100,
    canCreate: true,
    maxCharacters: 5,
  },
  pro: {
    id: 'pro',
    name: '프로',
    priceKrw: num('PRO_PRICE_KRW', 19900),
    costCapKrw: num('PRO_COST_CAP_KRW', 7000),
    model: planModel('MODEL_PRO', 'claude-opus-5'),
    maxTokens: 1000,
    historyTurns: 40,
    blurb: '몰입감 최우선. 최상위 모델로 연기합니다',
    features: ['최상위 모델(Opus 5)', '가장 긴 기억(40턴)', '내 캐릭터 30개 제작', '새 기능 우선 공개'],
    maxConversations: 500,
    canCreate: true,
    maxCharacters: 30,
  },
};

/** 한도를 다 쓴 사람이 추가로 사는 충전팩 (등록된 카드로 바로 결제) */
export const TOPUP_PACKS = {
  small: { id: 'small', name: '충전 소', amountKrw: num('TOPUP_SMALL_KRW', 3900), capKrw: num('TOPUP_SMALL_CAP_KRW', 1200) },
  large: { id: 'large', name: '충전 대', amountKrw: num('TOPUP_LARGE_KRW', 9900), capKrw: num('TOPUP_LARGE_CAP_KRW', 3500) },
};

export const PAID_PLANS = ['lite', 'pro'];

export function getPlan(id) {
  return PLANS[id] || PLANS.free;
}

/** 토큰 사용량 → 원화 원가 */
export function costKrw({ model, inputTokens = 0, outputTokens = 0, cacheReadTokens = 0, cacheWriteTokens = 0 }) {
  const price = MODEL_PRICING[model] || MODEL_PRICING['claude-opus-5'];
  const usd =
    (inputTokens * price.input +
      cacheWriteTokens * price.input * 1.25 +
      cacheReadTokens * price.input * 0.1 +
      outputTokens * price.output) /
    1_000_000;
  return usd * config.usdKrw;
}
