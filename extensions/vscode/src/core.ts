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

  /** Digital employees que a pessoa gerencia (só esses podem trabalhar no VS Code dela). */
  async manageableEmployees(): Promise<HangarEmployee[]> {
    const all = await (await this.req('/api/employees')).json() as HangarEmployee[];
    return all.filter(e => e.can_manage && !['offboarded', 'onboarding'].includes(e.status));
  }

  /** external: o VS Code passa a ser o worker (o token novo vem só nesta resposta); hangar: volta para a plataforma. */
  async setRuntime(slug: string, runtime: 'external' | 'hangar'): Promise<{ runtime: string; token?: string }> {
    return (await this.req(`/api/employees/${encodeURIComponent(slug)}/runtime`, {
      method: 'PUT', body: JSON.stringify({ runtime, rotate: runtime === 'external' }),
    })).json() as Promise<{ runtime: string; token?: string }>;
  }
}

// ------------------------------------------------------------------ posto de trabalho de um Digital employee
/* O VS Code trabalha como o worker externo de um Digital employee: busca as tarefas dele pelo heartbeat, pensa com o
   próprio funcionário por AG-UI (instruções, skills, MCPs e memória do cargo ficam na plataforma) e executa aqui as
   ferramentas do posto — arquivos, terminal e publicação no GitHub — perguntando à alçada antes do que muda algo. */

export interface HangarEmployee {
  slug: string; name: string; title: string; status: string; runtime: string; can_manage: boolean;
  tasks?: Record<string, number>;
}

export interface WorkerTask {
  id: number; title: string; body: string; run: number; url: string; language?: string;
  messages: { role: string; content: string }[];
  decisions: { id: number; kind: string; status: string; decision: string; tool: string }[];
  budget_usd: number; cost_usd: number; time_limit_min: number;
}

export interface GateResult { status: 'allowed' | 'waiting' | 'denied' | 'simulated'; message?: string; request_id?: number; action_type?: string }

export interface AguiMessage {
  id: string; role: 'user' | 'assistant' | 'tool' | 'system';
  content?: string;
  toolCalls?: { id: string; type: 'function'; function: { name: string; arguments: string } }[];
  toolCallId?: string;
}

export interface ToolSpec { name: string; description: string; parameters: object }

/** As ferramentas do posto. O tipo de cada uma na alçada vem da plataforma (vscode:<nome>). */
export const WORKSTATION_TOOLS: ToolSpec[] = [
  { name: 'list_files', description: 'Lista arquivos e pastas da pasta de trabalho (ignora .git, .venv, node_modules).',
    parameters: { type: 'object', properties: { path: { type: 'string', description: 'pasta relativa (padrão: .)' },
      depth: { type: 'integer', description: 'níveis (padrão 2, máx. 5)' } } } },
  { name: 'read_file', description: 'Lê um arquivo de texto da pasta de trabalho (até 20.000 caracteres; use start_line/end_line para trechos).',
    parameters: { type: 'object', required: ['path'], properties: { path: { type: 'string' },
      start_line: { type: 'integer' }, end_line: { type: 'integer' } } } },
  { name: 'search_files', description: 'Procura um texto (expressão regular) nos arquivos da pasta de trabalho.',
    parameters: { type: 'object', required: ['pattern'], properties: { pattern: { type: 'string' },
      glob: { type: 'string', description: 'ex.: **/*.py' } } } },
  { name: 'write_file', description: 'Cria ou substitui um arquivo da pasta de trabalho (cria as pastas). Abre no editor.',
    parameters: { type: 'object', required: ['path', 'content'], properties: { path: { type: 'string' }, content: { type: 'string' } } } },
  { name: 'edit_file', description: 'Troca um trecho exato (que aparece uma única vez) de um arquivo.',
    parameters: { type: 'object', required: ['path', 'old_string', 'new_string'], properties: { path: { type: 'string' },
      old_string: { type: 'string' }, new_string: { type: 'string' } } } },
  { name: 'run_command', description: 'Roda um comando no terminal da pasta de trabalho e devolve a saída (o fim dela, até 12.000 caracteres) e o código de saída. A pessoa vê o terminal ao vivo no VS Code.',
    parameters: { type: 'object', required: ['command'], properties: { command: { type: 'string' },
      cwd: { type: 'string', description: 'pasta relativa (padrão: .)' },
      timeout_s: { type: 'integer', description: 'limite em segundos (padrão 900, máx. 7200)' } } } },
  { name: 'publish_github', description: 'Publica a pasta de trabalho num repositório do GitHub da pessoa (cria o repositório se não existir, faz commit e push). Respeita o .gitignore. Precisa de aprovação.',
    parameters: { type: 'object', required: ['repo'], properties: { repo: { type: 'string', description: 'nome do repositório' },
      description: { type: 'string' }, public: { type: 'boolean', description: 'padrão true' },
      message: { type: 'string', description: 'mensagem do commit' } } } },
];

/** O que pergunta à alçada antes de executar (ler não pergunta). */
export const GATED = new Set(['write_file', 'edit_file', 'run_command', 'publish_github']);

/** Os argumentos que a alçada vê: a ação exata, sem o conteúdo inteiro de um arquivo. */
export function gateArgs(name: string, input: Record<string, unknown>): Record<string, unknown> {
  if (name === 'write_file') return { path: input.path, chars: String(input.content ?? '').length };
  if (name === 'edit_file') return { path: input.path };
  if (name === 'run_command') return { command: input.command, cwd: input.cwd ?? '.' };
  if (name === 'publish_github') return { repo: input.repo, public: input.public !== false, description: input.description ?? '' };
  return input;
}

export type AguiEvent =
  | { type: 'text'; text: string }
  | { type: 'server_tool'; id: string; name: string }
  | { type: 'client_call'; id: string; name: string; input: Record<string, unknown>; raw: string }
  | { type: 'usage'; value: Record<string, number> }
  | { type: 'task'; value: { status: string; cost_usd?: number; request?: number | null } }
  | { type: 'error'; message: string };

/** Lê o stream AG-UI. Texto sai na hora; uma chamada de ferramenta sem TOOL_CALL_RESULT no stream é do app (o
 *  runtime executou as dele e devolveu as nossas para executarmos aqui), e sai no fim. */
export async function* parseAgui(chunks: AsyncIterable<string>): AsyncGenerator<AguiEvent> {
  let buf = '';
  const calls = new Map<string, { name: string; args: string }>();
  const answered = new Set<string>();
  const handle = function* (ev: Record<string, unknown>): Generator<AguiEvent> {
    const t = ev.type;
    if (t === 'TEXT_MESSAGE_CONTENT' && typeof ev.delta === 'string') yield { type: 'text', text: ev.delta };
    else if (t === 'TOOL_CALL_START') calls.set(String(ev.toolCallId), { name: String(ev.toolCallName ?? ''), args: '' });
    else if (t === 'TOOL_CALL_ARGS') { const c = calls.get(String(ev.toolCallId)); if (c) c.args += String(ev.delta ?? ''); }
    else if (t === 'TOOL_CALL_RESULT') {
      answered.add(String(ev.toolCallId));
      yield { type: 'server_tool', id: String(ev.toolCallId), name: calls.get(String(ev.toolCallId))?.name ?? '' };
    } else if (t === 'RUN_ERROR') yield { type: 'error', message: String(ev.message ?? 'erro no agente') };
    else if (t === 'CUSTOM' && ev.name === 'hangar.usage') yield { type: 'usage', value: (ev.value ?? {}) as Record<string, number> };
    else if (t === 'CUSTOM' && ev.name === 'hangar.task') yield { type: 'task', value: ev.value as { status: string } };
  };
  for await (const chunk of chunks) {
    buf += chunk;
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line.startsWith('data: {')) continue;
      let ev: Record<string, unknown>;
      try { ev = JSON.parse(line.slice(6)); } catch { continue; }
      yield* handle(ev);
    }
  }
  for (const [id, c] of calls) {
    if (answered.has(id)) continue;
    let input: Record<string, unknown> = {};
    try { input = c.args ? JSON.parse(c.args) : {}; } catch { input = { _raw: c.args }; }
    yield { type: 'client_call', id, name: c.name, input, raw: c.args || '{}' };
  }
}

/** A conversa da tarefa (formato OpenAI, como o heartbeat devolve) -> mensagens AG-UI. */
export function toAguiMessages(messages: { role: string; content: string }[]): AguiMessage[] {
  return messages.filter(m => ['user', 'assistant', 'system'].includes(m.role))
    .map((m, i) => ({ id: `h${i}`, role: m.role as AguiMessage['role'], content: String(m.content ?? '') }));
}

/** Mantém a conversa dentro de um tamanho: as saídas de ferramenta mais antigas viram um resumo curto (o começo e o
 *  fim), as recentes ficam inteiras. */
export function compact(messages: AguiMessage[], maxChars = 180_000, keepRecent = 12): AguiMessage[] {
  const size = (ms: AguiMessage[]) => ms.reduce((n, m) => n + (m.content?.length ?? 0) + JSON.stringify(m.toolCalls ?? '').length, 0);
  if (size(messages) <= maxChars) return messages;
  const out = messages.map(m => ({ ...m }));
  const tools = out.map((m, i) => (m.role === 'tool' ? i : -1)).filter(i => i >= 0);
  for (const i of tools.slice(0, Math.max(0, tools.length - keepRecent))) {
    const c = out[i].content ?? '';
    if (c.length > 800) out[i].content = `${c.slice(0, 400)}\n…[saída antiga resumida: ${c.length} caracteres]…\n${c.slice(-300)}`;
    if (size(out) <= maxChars) break;
  }
  return out;
}

/** O resultado de uma ação que voltou de uma decisão que não a liberou: o texto de quem decidiu ("DECISÃO #n: …", que
 *  a plataforma põe na conversa da tarefa), ou um aviso genérico. undefined: a decisão liberou (a ação roda de novo). */
export function decisionResult(d: { id: number; decision: string } | undefined, arrived: { content: string }[]): string | undefined {
  if (!d || !d.decision || d.decision.startsWith('approve')) return undefined;
  const said = arrived.find(m => m.content.startsWith(`DECISÃO #${d.id}:`));
  return said?.content ?? `DECISÃO #${d.id}: ${d.decision === 'instruct' ? 'INSTRUÇÃO' : 'RECUSADO'}. `
    + 'Não execute a ação como estava; siga sem ela ou explique na entrega.';
}

/** Fim de um texto longo (a parte que importa de uma saída de terminal). */
export function tail(text: string, max = 12_000): string {
  return text.length <= max ? text : `…[${text.length - max} caracteres antes]…\n${text.slice(-max)}`;
}

/** Cliente do worker: o token do funcionário (ewk_…) só fala com as tarefas dele. */
export class WorkerClient {
  constructor(readonly base: string, private readonly token: string, private readonly fetchImpl: FetchLike = fetch) {}

  private async req(path: string, body: object, signal?: AbortSignal): Promise<Response> {
    const r = await this.fetchImpl(this.base.replace(/\/$/, '') + path, {
      method: 'POST', signal, body: JSON.stringify(body),
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
    });
    if (!r.ok) {
      let msg = r.statusText;
      try { const j = await r.json() as { detail?: string; error?: string }; msg = j.detail ?? j.error ?? msg; } catch { /* corpo não-JSON */ }
      throw new HangarError(msg || `HTTP ${r.status}`, r.status);
    }
    return r;
  }

  async heartbeat(worker: object, wantTask = true): Promise<{ employee: string; name: string; status: string; task: WorkerTask | null; next_heartbeat_s: number }> {
    return (await this.req('/hooks/worker/heartbeat', { worker, want_task: wantTask })).json() as Promise<{ employee: string; name: string; status: string; task: WorkerTask | null; next_heartbeat_s: number }>;
  }

  async gate(taskId: number, tool: string, args: object, rationale = ''): Promise<GateResult> {
    return (await this.req(`/hooks/worker/tasks/${taskId}/gate`, { tool, args, rationale })).json() as Promise<GateResult>;
  }

  async progress(taskId: number, note = ''): Promise<{ status: string; cost_usd: number; stop: boolean }> {
    return (await this.req(`/hooks/worker/tasks/${taskId}/progress`, { note })).json() as Promise<{ status: string; cost_usd: number; stop: boolean }>;
  }

  async result(taskId: number, status: 'done' | 'failed' | 'waiting', result = '', error = ''): Promise<{ status: string }> {
    return (await this.req(`/hooks/worker/tasks/${taskId}/result`, { status, result, error })).json() as Promise<{ status: string }>;
  }

  async *agui(taskId: number, body: object, signal?: AbortSignal): AsyncGenerator<AguiEvent> {
    const r = await this.req(`/hooks/worker/tasks/${taskId}/agui`, body, signal);
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
    yield* parseAgui(chunks());
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
