// Claude 호출부. 스트리밍으로 받아 화면에 흘려주고, 끝나면 실제 토큰 사용량을 돌려줍니다.
import Anthropic from '@anthropic-ai/sdk';
import { config, EFFORT_MODELS } from './config.js';

let client;
export function getClient() {
  if (!client) client = new Anthropic({ apiKey: config.anthropicApiKey || undefined });
  return client;
}

export const demoMode = () => process.env.DEMO_MODE === '1' || (!config.anthropicApiKey && process.env.NODE_ENV !== 'production');

const REFUSAL_BETA = 'server-side-fallback-2026-07-01';

function buildParams({ model, maxTokens, system, messages }) {
  const params = {
    model,
    max_tokens: maxTokens,
    // 시스템 프롬프트는 요청마다 같으므로 캐시 대상으로 표시해 둡니다.
    system: [{ type: 'text', text: system, cache_control: { type: 'ephemeral' } }],
    messages,
  };
  // 카피 생성은 깊은 추론이 필요 없어 effort 를 낮춰 원가와 대기시간을 줄입니다.
  if (EFFORT_MODELS.has(model)) params.output_config = { effort: 'low' };
  return params;
}

/**
 * 답변을 스트리밍합니다.
 * @returns {Promise<{text:string, usage:object, stopReason:string, refusal?:string}>}
 */
export async function streamAnswer({ model, maxTokens, system, messages, onText }) {
  if (demoMode()) return demoAnswer({ model, maxTokens, onText });

  const params = buildParams({ model, maxTokens, system, messages });
  let stream;
  try {
    // Opus 5 는 안전 분류기 거절 시 서버측 대체 모델로 넘어가도록 켜 둡니다.
    stream = getClient().beta.messages.stream({ ...params, betas: [REFUSAL_BETA], fallbacks: 'default' });
  } catch {
    stream = getClient().messages.stream(params);
  }

  let text = '';
  try {
    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
        text += event.delta.text;
        onText?.(event.delta.text);
      }
    }
  } catch (err) {
    // 베타 플래그를 조직에서 못 쓰는 경우 한 번만 표준 경로로 재시도합니다.
    if (!text && isBetaRejection(err)) return streamStandard({ params, onText });
    throw err;
  }

  const final = await stream.finalMessage();
  if (final.stop_reason === 'refusal') {
    return { text, usage: final.usage, stopReason: 'refusal', refusal: final.stop_details?.category || null };
  }
  return { text, usage: final.usage, stopReason: final.stop_reason };
}

async function streamStandard({ params, onText }) {
  const stream = getClient().messages.stream(params);
  let text = '';
  for await (const event of stream) {
    if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
      text += event.delta.text;
      onText?.(event.delta.text);
    }
  }
  const final = await stream.finalMessage();
  return { text, usage: final.usage, stopReason: final.stop_reason };
}

function isBetaRejection(err) {
  const status = err?.status ?? err?.response?.status;
  if (status !== 400 && status !== 404) return false;
  return /beta|fallback|unsupported/i.test(String(err?.message || ''));
}

/** API 키 없이도 화면 흐름을 확인할 수 있게 하는 로컬 데모 응답 */
async function demoAnswer({ maxTokens, onText }) {
  const sample = [
    '*잠시 말이 없다가 고개를 든다*\n\n',
    '"...데모 모드라서 지금은 내가 제대로 대답을 못 해."\n\n',
    '*손끝으로 탁자를 톡톡 두드린다*\n\n',
    '"서버에 ANTHROPIC_API_KEY 를 넣고 다시 켜면, 그때부턴 진짜 나로 얘기할게."',
  ];
  for (const chunk of sample) {
    onText?.(chunk);
    await new Promise((r) => setTimeout(r, 60));
  }
  return {
    text: sample.join(''),
    usage: {
      input_tokens: 900,
      output_tokens: Math.min(120, maxTokens),
      cache_read_input_tokens: 0,
      cache_creation_input_tokens: 0,
    },
    stopReason: 'end_turn',
    demo: true,
  };
}

/** 첫 질문으로 대화 제목을 짧게 만듭니다(실패해도 서비스에 영향 없음). */
export function titleFromText(text) {
  const line = String(text).split('\n').find((l) => l.trim()) || '새 대화';
  return line.replace(/^[#\-*\s]+/, '').slice(0, 40);
}
