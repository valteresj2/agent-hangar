/* Lógica da extensão que não depende do VS Code (testável com `node --test`): conversão das mensagens e ferramentas
   do chat do VS Code para o formato OpenAI, leitura do stream SSE do gateway e o cliente HTTP do Agent Hangar. */
import { createHash, randomBytes } from 'crypto';

export type Env = 'prod' | 'stage';

// Formas das partes do chat do VS Code (reconhecidas pelo formato, sem importar o módulo vscode)
interface TextLike { value: string }
interface ToolCallLike { callId: string; name: string; input: object }
interface ToolResultLike { callId: string; content: unknown[] }
export interface ChatMessageLike { role: number; content: ReadonlyArray<unknown> }
export interface ChatToolLike { name: string; description: string; inputSchema?: object }

const isText = (p: unknown): p is TextLike => typeof (p as TextLike)?.value === 'string';
const isToolCall = (p: unknown): p is ToolCallLike =>
  typeof (p as ToolCallLike)?.callId === 'string' && typeof (p as ToolCallLike)?.name === 'string' && 'input' in (p as object);
const isToolResult = (p: unknown): p is ToolResultLike =>
  typeof (p as ToolResultLike)?.callId === 'string' && Array.isArray((p as ToolResultLike)?.content) && !('name' in (p as object));

export const ROLE = { User: 1, Assistant: 2, System: 3 } as const;

export interface OpenAIMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | null;
  tool_calls?: { id: string; type: 'function'; function: { name: string; arguments: string } }[];
  tool_call_id?: string;
}

function resultText(content: unknown[]): string {
  return content.map(c => (isText(c) ? c.value : typeof c === 'string' ? c : JSON.stringify(c))).join('\n');
}

/** Mensagens do chat do VS Code -> OpenAI. Resultados de ferramentas viram mensagens `tool` (antes do texto do
 *  usuário da mesma mensagem); chamadas de ferramenta do assistente viram `tool_calls`. */
export function toOpenAIMessages(messages: readonly ChatMessageLike[]): OpenAIMessage[] {
  const out: OpenAIMessage[] = [];
  for (const m of messages) {
    const text = m.content.filter(isText).map(p => p.value).join('');
    if (m.role === ROLE.Assistant) {
      const calls = m.content.filter(isToolCall).map(c => ({
        id: c.callId, type: 'function' as const, function: { name: c.name, arguments: JSON.stringify(c.input ?? {}) },
      }));
      out.push({ role: 'assistant', content: text || (calls.length ? null : ''), ...(calls.length ? { tool_calls: calls } : {}) });
      continue;
    }
    for (const r of m.content.filter(isToolResult)) {
      out.push({ role: 'tool', tool_call_id: r.callId, content: resultText(r.content) });
    }
    if (text) out.push({ role: m.role === ROLE.System ? 'system' : 'user', content: text });
  }
  return out;
}

export function toOpenAITools(tools: readonly ChatToolLike[] | undefined) {
  return (tools ?? []).map(t => ({
    type: 'function' as const,
    function: { name: t.name, description: t.description ?? '', parameters: t.inputSchema ?? { type: 'object', properties: {} } },
  }));
}

export type StreamEvent =
  | { type: 'text'; text: string }
  | { type: 'tool_call'; id: string; name: string; input: object }
  | { type: 'done'; finish: string | null; usage?: Record<string, number> };

/** Lê o SSE do gateway (formato OpenAI). Texto sai assim que chega; as tool_calls saem inteiras no fim. */
export async function* parseSSE(chunks: AsyncIterable<string>): AsyncGenerator<StreamEvent> {
  let buf = '';
  let finish: string | null = null;
  let usage: Record<string, number> | undefined;
  const calls = new Map<number, { id: string; name: string; args: string }>();
  for await (const chunk of chunks) {
    buf += chunk;
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line.startsWith('data: {')) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.usage) usage = ev.usage;
      for (const ch of ev.choices ?? []) {
        const d = ch.delta ?? {};
        if (d.content) yield { type: 'text', text: d.content };
        for (const tc of d.tool_calls ?? []) {
          const c = calls.get(tc.index ?? 0) ?? { id: '', name: '', args: '' };
          c.id = tc.id || c.id;
          c.name += tc.function?.name ?? '';
          c.args += tc.function?.arguments ?? '';
          calls.set(tc.index ?? 0, c);
        }
        if (ch.finish_reason) finish = ch.finish_reason;
      }
    }
  }
  for (const [, c] of [...calls.entries()].sort((a, b) => a[0] - b[0])) {
    let input: object = {};
    try { input = c.args ? JSON.parse(c.args) : {}; } catch { input = { _raw: c.args }; }
    yield { type: 'tool_call', id: c.id, name: c.name, input };
  }
  yield { type: 'done', finish, usage };
}

export function pkce() {
  const verifier = randomBytes(32).toString('base64url');
  const challenge = createHash('sha256').update(verifier).digest('base64url');
  return { verifier, challenge, state: randomBytes(12).toString('base64url') };
}

export interface HangarAgent {
  slug: string; name: string; objective: string; version: number; team?: { name: string } | null;
  prod: boolean; stage: boolean; harness?: unknown; permissions?: string[];
}

export class HangarError extends Error {
  constructor(message: string, readonly status = 0) { super(message); }
}

type FetchLike = typeof fetch;

/** Cliente HTTP do Agent Hangar com o token pessoal (escopo user) da pessoa. */
export class HangarClient {
  constructor(readonly base: string, private readonly token: string, private readonly fetchImpl: FetchLike = fetch) {}

  private async req(path: string, init: RequestInit = {}): Promise<Response> {
    const r = await this.fetchImpl(this.base.replace(/\/$/, '') + path, {
      ...init, headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    });
    if (!r.ok) {
      let msg = r.statusText;
      try { const j = await r.json() as { detail?: string; error?: string | { message?: string } }; msg = j.detail ?? (typeof j.error === 'string' ? j.error : j.error?.message) ?? msg; } catch { /* corpo não-JSON */ }
      throw new HangarError(msg || `HTTP ${r.status}`, r.status);
    }
    return r;
  }

  async me(): Promise<{ user?: { name: string; email: string } | null; name: string }> {
    return (await this.req('/api/me')).json() as Promise<{ user?: { name: string; email: string } | null; name: string }>;
  }

  /** Agentes de chat que a pessoa pode usar e que estão no ar no ambiente pedido (stage exige poder editar). */
  async usableAgents(env: Env): Promise<HangarAgent[]> {
    const all = await (await this.req('/api/agents')).json() as HangarAgent[];
    return all.filter(a => !a.harness && (env === 'prod'
      ? a.prod && (a.permissions ?? []).includes('consume')
      : a.stage && (a.permissions ?? []).includes('edit')));
  }

  async *chat(slug: string, env: Env, body: object, signal?: AbortSignal, session?: string): AsyncGenerator<StreamEvent> {
    const prefix = env === 'prod' ? 'gw' : 'gw-stage';
    const r = await this.req(`/${prefix}/${encodeURIComponent(slug)}/v1/chat/completions`, {
      method: 'POST', signal, body: JSON.stringify({ model: slug, stream: true, ...body }),
      headers: { 'X-Channel': 'vscode', ...(session ? { 'X-Session-Id': session } : {}) },
    });
    if (!r.body) throw new HangarError('resposta sem corpo');
    const decoder = new TextDecoder();
    const reader = r.body.getReader();
    async function* chunks() {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return;
        yield decoder.decode(value, { stream: true });
      }
    }
    yield* parseSSE(chunks());
  }

  async testConnection(slug: string, env: Env): Promise<{ ok: boolean; steps: { name: string; ok: boolean; detail: string; ms?: number }[] }> {
    return (await this.req(`/api/agents/${encodeURIComponent(slug)}/connections/test`, {
      method: 'POST', body: JSON.stringify({ env }),
    })).json() as Promise<{ ok: boolean; steps: { name: string; ok: boolean; detail: string; ms?: number }[] }>;
  }

  async revokeKey(id: number): Promise<void> {
    await this.req(`/api/keys/${id}`, { method: 'DELETE' });
  }
}

/** Troca o código do portal + verifier pelo token pessoal (rota aberta: o código assinado é a credencial). */
export async function exchangeCode(base: string, code: string, verifier: string, fetchImpl: FetchLike = fetch) {
  const r = await fetchImpl(base.replace(/\/$/, '') + '/api/auth/vscode/token', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, verifier }),
  });
  const j = await r.json() as { token?: string; key_id?: number; user?: { name: string; email: string }; detail?: string };
  if (!r.ok || !j.token) throw new HangarError(j.detail ?? `HTTP ${r.status}`, r.status);
  return j as { token: string; key_id: number; user: { name: string; email: string } };
}
