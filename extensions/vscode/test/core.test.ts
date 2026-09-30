/* Testes da lógica pura da extensão (sem VS Code): `npm test`. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';

import { HangarClient, parseSSE, pkce, ROLE, toOpenAIMessages, toOpenAITools } from '../src/core';

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
