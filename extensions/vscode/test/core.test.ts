/* Testes da lógica pura da extensão (sem VS Code): `npm test`. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';

import {
  compact, decisionResult, etaFrom, gateArgs, HangarClient, parseAgui, parseSSE, pkce, readProgress, ROLE, toAguiMessages, toolOk, toOpenAIMessages,
  toOpenAITools, WorkerClient,
} from '../src/core';

// partes no formato das classes do VS Code (LanguageModelTextPart, ToolCallPart, ToolResultPart)
const text = (value: string) => ({ value });
const call = (callId: string, name: string, input: object) => ({ callId, name, input });
const result = (callId: string, value: string) => ({ callId, content: [{ value }] });

test('mensagens do chat do VS Code viram o formato OpenAI', () => {
  const out = toOpenAIMessages([
    { role: ROLE.User, content: [text('corrija o bug')] },
    { role: ROLE.Assistant, content: [text('vou ler'), call('c1', 'read_file', { path: 'a.py' })] },
    { role: ROLE.User, content: [result('c1', 'print(1)')] },
  ]);
  assert.deepEqual(out, [
    { role: 'user', content: 'corrija o bug' },
    { role: 'assistant', content: 'vou ler', tool_calls: [{ id: 'c1', type: 'function', function: { name: 'read_file', arguments: '{"path":"a.py"}' } }] },
    { role: 'tool', tool_call_id: 'c1', content: 'print(1)' },
  ]);
});

test('assistente só com chamada de ferramenta tem content null', () => {
  const [m] = toOpenAIMessages([{ role: ROLE.Assistant, content: [call('c2', 'run', {})] }]);
  assert.equal(m.content, null);
  assert.equal(m.tool_calls?.[0].id, 'c2');
});

test('ferramentas do VS Code viram functions', () => {
  assert.deepEqual(toOpenAITools([{ name: 'read_file', description: 'lê', inputSchema: { type: 'object' } }, { name: 'x', description: '' }]), [
    { type: 'function', function: { name: 'read_file', description: 'lê', parameters: { type: 'object' } } },
    { type: 'function', function: { name: 'x', description: '', parameters: { type: 'object', properties: {} } } },
  ]);
});

async function* from(parts: string[]) { for (const p of parts) yield p; }

test('SSE: texto em pedaços e tool_calls montadas no fim', async () => {
  const ev = (o: object) => `data: ${JSON.stringify(o)}\n\n`;
  const lines = [
    ev({ choices: [{ delta: { role: 'assistant', content: '' } }] }),
    ev({ choices: [{ delta: { content: 'Vou ' } }] }) + ev({ choices: [{ delta: { content: 'ler.' } }] }),
    ev({ choices: [{ delta: { tool_calls: [{ index: 0, id: 'c1', type: 'function', function: { name: 'read_', arguments: '{"pa' } }] } }] }),
    ev({ choices: [{ delta: { tool_calls: [{ index: 0, function: { name: 'file', arguments: 'th":"a.py"}' } }] } }] }),
    ev({ choices: [{ delta: {}, finish_reason: 'tool_calls' }], usage: { total_tokens: 12 } }),
    'data: [DONE]\n\n',
  ];
  // corta no meio das linhas para simular a rede
  const joined = lines.join('');
  const chunks = [joined.slice(0, 37), joined.slice(37, 140), joined.slice(140)];
  const out = [];
  for await (const e of parseSSE(from(chunks))) out.push(e);
  assert.deepEqual(out, [
    { type: 'text', text: 'Vou ' }, { type: 'text', text: 'ler.' },
    { type: 'tool_call', id: 'c1', name: 'read_file', input: { path: 'a.py' } },
    { type: 'done', finish: 'tool_calls', usage: { total_tokens: 12 } },
  ]);
});

test('PKCE: challenge é o sha256 do verifier em base64url', () => {
  const p = pkce();
  assert.equal(p.challenge, createHash('sha256').update(p.verifier).digest('base64url'));
  assert.ok(p.verifier.length >= 43 && p.state.length >= 8);
});

test('usableAgents: prod exige consume e estar no ar; stage exige edit; harness fica de fora', async () => {
  const agents = [
    { slug: 'a', prod: true, stage: false, permissions: ['view', 'consume'] },
    { slug: 'b', prod: false, stage: true, permissions: ['view', 'consume', 'edit'] },
    { slug: 'c', prod: true, stage: true, permissions: ['view'] },
    { slug: 'd', prod: true, stage: true, permissions: ['consume', 'edit'], harness: { id: 'codex' } },
  ];
  const fake = (async () => new Response(JSON.stringify(agents), { status: 200 })) as unknown as typeof fetch;
  const c = new HangarClient('http://h', 't', fake);
  assert.deepEqual((await c.usableAgents('prod')).map(a => a.slug), ['a']);
  assert.deepEqual((await c.usableAgents('stage')).map(a => a.slug), ['b']);
});

// ------------------------------------------------------------------ posto de trabalho (Digital employee por AG-UI)
async function* feed(...parts: string[]) { for (const p of parts) yield p; }
const ev = (e: object) => `data: ${JSON.stringify(e)}\n\n`;

test('AG-UI: texto na hora, ferramenta do servidor com resultado, as do app saem no fim', async () => {
  const out = [];
  for await (const e of parseAgui(feed(
    ev({ type: 'RUN_STARTED' }), ev({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'm', delta: 'Vou ' }),
    ev({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'm', delta: 'treinar.' }),
    ev({ type: 'TOOL_CALL_START', toolCallId: 's1', toolCallName: 'memory_recall' }),
    ev({ type: 'TOOL_CALL_ARGS', toolCallId: 's1', delta: '{}' }), ev({ type: 'TOOL_CALL_END', toolCallId: 's1' }),
    ev({ type: 'TOOL_CALL_RESULT', toolCallId: 's1', content: 'nada' }),
    ev({ type: 'TOOL_CALL_START', toolCallId: 'c1', toolCallName: 'run_command' }),
    // argumentos partidos entre pedaços do stream
    'data: {"type":"TOOL_CALL_ARGS","toolCallId":"c1","delta":"{\\"command\\": \\"python', ' --version\\"}"}\n\n',
    ev({ type: 'TOOL_CALL_END', toolCallId: 'c1' }),
    ev({ type: 'CUSTOM', name: 'hangar.usage', value: { total_tokens: 10, cost_usd: 0.01 } }),
    // uma ferramenta da plataforma sem TOOL_CALL_RESULT no stream (repasse): ela já executou, o posto ignora
    ev({ type: 'TOOL_CALL_START', toolCallId: 'p1', toolCallName: 'handoff_task' }),
    ev({ type: 'TOOL_CALL_ARGS', toolCallId: 'p1', delta: '{"to":"cientista-de-dados","title":"x"}' }), ev({ type: 'TOOL_CALL_END', toolCallId: 'p1' }),
    ev({ type: 'RUN_FINISHED' }), ev({ type: 'CUSTOM', name: 'hangar.task', value: { status: 'in_progress' } }),
  ))) out.push(e);
  assert.deepEqual(out.filter(e => e.type === 'text').map(e => (e as { text: string }).text).join(''), 'Vou treinar.');
  assert.deepEqual(out.find(e => e.type === 'server_tool'), { type: 'server_tool', id: 's1', name: 'memory_recall' });
  const calls = out.filter(e => e.type === 'client_call');
  assert.equal(calls.length, 1);
  assert.deepEqual((calls[0] as { input: object }).input, { command: 'python --version' });
  assert.deepEqual(out.find(e => e.type === 'task'), { type: 'task', value: { status: 'in_progress' } });
  assert.equal(out.at(-1)?.type, 'client_call');  // as do app vêm depois de tudo
});

test('a alçada vê a ação, não o conteúdo inteiro do arquivo', () => {
  assert.deepEqual(gateArgs('write_file', { path: 'a.py', content: 'x'.repeat(50) }), { path: 'a.py', chars: 50 });
  assert.deepEqual(gateArgs('run_command', { command: 'pytest' }), { command: 'pytest', cwd: '.' });
  assert.deepEqual(gateArgs('publish_github', { repo: 'r' }), { repo: 'r', public: true, description: '' });
});

test('conversa da tarefa vira AG-UI e as saídas antigas encolhem', () => {
  const msgs = toAguiMessages([{ role: 'user', content: 'tarefa' }, { role: 'assistant', content: 'ok' }]);
  assert.deepEqual(msgs.map(m => m.role), ['user', 'assistant']);
  const long = Array.from({ length: 20 }, (_, i) => ({ id: `t${i}`, role: 'tool' as const, toolCallId: `c${i}`, content: 'x'.repeat(20_000) }));
  const small = compact([...msgs, ...long], 100_000, 3);
  assert.ok(small.slice(-3).every(m => m.content?.length === 20_000));  // as recentes ficam inteiras
  assert.ok((small[2].content ?? '').includes('saída antiga resumida'));
  assert.equal(long[0].content.length, 20_000);  // não muda o original
});

test('WorkerClient: token do funcionário, erros viram HangarError com status', async () => {
  const seen: { url: string; auth: string; body: unknown }[] = [];
  const fake = (async (url: string, init: RequestInit) => {
    seen.push({ url, auth: (init.headers as Record<string, string>).Authorization, body: JSON.parse(String(init.body)) });
    if (url.endsWith('/gate')) return new Response(JSON.stringify({ detail: 'a tarefa não está com o worker' }), { status: 409 });
    return new Response(JSON.stringify({ employee: 'cd', task: null, next_heartbeat_s: 5 }), { status: 200 });
  }) as typeof fetch;
  const c = new WorkerClient('http://h/', 'ewk_x', fake);
  assert.equal((await c.heartbeat({ name: 'vs' })).employee, 'cd');
  assert.equal(seen[0].url, 'http://h/hooks/worker/heartbeat');
  assert.equal(seen[0].auth, 'Bearer ewk_x');
  await assert.rejects(c.gate(7, 'vscode:run_command', {}), (e: Error & { status: number }) => e.status === 409 && /worker/.test(e.message));
});

test('decisão que não libera: o texto de quem decidiu volta como resultado da ação', () => {
  const arrived = [{ content: 'DECISÃO #575: INSTRUÇÃO de ana: apague catboost_info/ e peça de novo' }];
  assert.equal(decisionResult({ id: 575, decision: 'instruct' }, arrived), arrived[0].content);
  assert.match(decisionResult({ id: 9, decision: 'reject' }, [])!, /^DECISÃO #9: RECUSADO/);
  assert.equal(decisionResult({ id: 575, decision: 'approve' }, arrived), undefined);
  assert.equal(decisionResult(undefined, arrived), undefined);
});

test('progresso de um comando longo: PROGRESS, tqdm e pip, com o tempo que falta', () => {
  assert.deepEqual(readProgress('baixando\nPROGRESS 12/40 baixando os arquivos\n'),
    { done: 12, total: 40, unit: '', label: 'baixando os arquivos' });
  assert.deepEqual(readProgress('PROGRESS: 45% escorando'), { done: 45, total: 100, unit: '%', label: 'escorando' });
  // tqdm reescreve a linha com \r: vale a última
  const tq = 'Escorando:  10%|█         | 2/20 [00:01<00:09, 2.00file/s]\rEscorando:  45%|████▌     | 9/20 [00:10<00:12, 1.10file/s]';
  assert.deepEqual(readProgress(tq), { done: 9, total: 20, unit: 'file', label: 'Escorando', etaS: 12 });
  assert.deepEqual(readProgress(' 50%|█████     | 5.0k/10.0k [01:00<1:02:03, 83.3it/s]'),
    { done: 5000, total: 10000, unit: '', label: '', etaS: 3723 });
  assert.equal(readProgress('  3%|▎ | 1/30 [00:00<?, ?it/s]')?.etaS, undefined);
  assert.deepEqual(readProgress('   \x1b[32m5.2/10.0 MB\x1b[0m 3.1 MB/s eta 0:00:02'),
    { done: 5.2, total: 10, unit: 'MB', label: '', etaS: 2 });
  assert.equal(readProgress('Collecting pandas\nInstalled 3 packages in 50%  of the time'), undefined);
  assert.equal(etaFrom(10, 40, 20_000), 60);
  assert.equal(etaFrom(40, 40, 20_000), 0);
  assert.equal(etaFrom(0, 40, 20_000), undefined);
  assert.equal(etaFrom(5, undefined, 20_000), undefined);
});

test('a ferramenta deu certo? pelo texto que ela devolveu ao agente', () => {
  assert.equal(toolOk('código de saída: 0 · 3s\nok'), true);
  assert.equal(toolOk('código de saída: 1 · 3s\nTraceback'), false);
  assert.equal(toolOk('código de saída: null (interrompido: passou de 900s) · 900s'), false);
  assert.equal(toolOk('código de saída: 10 · 1s'), false);
  assert.equal(toolOk('erro: fora da pasta de trabalho: ../x'), false);
  assert.equal(toolOk('NEGADO pela alçada: …'), false);
  assert.equal(toolOk('DECISÃO #9: RECUSADO. Não execute'), false);
  assert.equal(toolOk('ok: relatorio.md (120 caracteres)'), true);
});

test('WorkerClient: a ferramenta e o trabalho longo vão no progress', async () => {
  const bodies: unknown[] = [];
  const fake = (async (_url: string, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ status: 'in_progress', cost_usd: 0, stop: false }), { status: 200 });
  }) as typeof fetch;
  const c = new WorkerClient('http://h', 'ewk_x', fake);
  await c.progress(3, '', { tool: { name: 'run_command', summary: 'python a.py', ok: true, ms: 10 } });
  await c.progress(3, '', { job: { id: 'cmd-1', label: 'a', done: 1, total: 2, unit: '', eta_s: 5, state: 'running' } });
  assert.deepEqual(bodies[0], { note: '', tool: { name: 'run_command', summary: 'python a.py', ok: true, ms: 10 } });
  assert.equal((bodies[1] as { job: { eta_s: number } }).job.eta_s, 5);
});
