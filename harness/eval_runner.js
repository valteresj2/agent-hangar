/* Runner da avaliação de código (fase de testes em stage). Roda num container efêmero da imagem harness-base e faz o
   papel do editor (VS Code, Cline…): monta o mini-projeto do caso, conversa com a versão em STAGE do agente pelo proxy
   interno da central oferecendo ferramentas de arquivo e terminal, executa as chamadas AQUI (no sandbox) e, no fim,
   roda o comando de verificação. O resultado volta para a central em /result.

   Ambiente: EVAL_URL (proxy + token de uso único), EVAL_TASK, EVAL_FILES (JSON caminho->conteúdo), EVAL_CHECK,
   EVAL_PROTECTED (JSON), EVAL_MAX_ROUNDS. Sem dependências além do Node 22. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const URL_ = process.env.EVAL_URL;
const WORK = '/workspace/eval';
const MAX_ROUNDS = Number(process.env.EVAL_MAX_ROUNDS || 30);
const OUT_LIMIT = 8000;
const files = JSON.parse(process.env.EVAL_FILES || '{}');
const protectedFiles = JSON.parse(process.env.EVAL_PROTECTED || '[]');

const TOOLS = [
  { name: 'list_files', description: 'Lista os arquivos do projeto aberto (caminhos relativos).', parameters: { type: 'object', properties: {} } },
  { name: 'read_file', description: 'Lê um arquivo do projeto.', parameters: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] } },
  { name: 'write_file', description: 'Cria ou substitui um arquivo do projeto com o conteúdo completo.', parameters: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path', 'content'] } },
  { name: 'run_command', description: 'Roda um comando no terminal (bash), na raiz do projeto. Tempo máximo: 120 s.', parameters: { type: 'object', properties: { command: { type: 'string' } }, required: ['command'] } },
].map(f => ({ type: 'function', function: f }));

const inside = p => {
  const full = path.resolve(WORK, p || '');
  if (full !== WORK && !full.startsWith(WORK + path.sep)) throw new Error('caminho fora do projeto');
  return full;
};
const hash = p => { try { return crypto.createHash('sha256').update(fs.readFileSync(inside(p))).digest('hex'); } catch { return null; } };
const walk = dir => fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => {
  if (['node_modules', '__pycache__', '.git', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.venv'].includes(e.name)) return [];
  const full = path.join(dir, e.name);
  return e.isDirectory() ? walk(full) : [path.relative(WORK, full)];
});
const clip = s => (s.length > OUT_LIMIT ? s.slice(0, 2000) + `\n…[${s.length - OUT_LIMIT} caracteres omitidos]…\n` + s.slice(-(OUT_LIMIT - 2000)) : s);

function sh(cmd, timeout = 120000) {
  const r = spawnSync('bash', ['-lc', cmd], { cwd: WORK, encoding: 'utf8', timeout, maxBuffer: 10 * 1024 * 1024 });
  const timedOut = r.error && r.error.code === 'ETIMEDOUT';
  return { code: timedOut ? 124 : (r.status ?? 1), out: clip(`${r.stdout || ''}${r.stderr || ''}${timedOut ? '\n[tempo esgotado]' : ''}`) };
}

function runTool(name, a) {
  try {
    if (name === 'list_files') return walk(WORK).join('\n') || '(vazio)';
    if (name === 'read_file') return clip(fs.readFileSync(inside(a.path), 'utf8'));
    if (name === 'write_file') {
      fs.mkdirSync(path.dirname(inside(a.path)), { recursive: true });
      fs.writeFileSync(inside(a.path), String(a.content ?? ''));
      return `ok: ${a.path} gravado (${String(a.content ?? '').length} caracteres)`;
    }
    if (name === 'run_command') { const r = sh(String(a.command || '')); return `exit=${r.code}\n${r.out}`; }
    return `ferramenta desconhecida: ${name}`;
  } catch (e) { return `erro: ${e.message}`; }
}

async function post(p, body) {
  const r = await fetch(URL_ + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const text = await r.text();
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : {};
}

(async () => {
  const result = { rounds: 0, tool_calls: [], final: '', check_exit: null, check_output: '', protected_changed: [], changed_files: [], error: '' };
  try {
    fs.mkdirSync(WORK, { recursive: true });
    for (const [p, content] of Object.entries(files)) {
      fs.mkdirSync(path.dirname(inside(p)), { recursive: true });
      fs.writeFileSync(inside(p), content);
    }
    const before = Object.fromEntries(Object.keys(files).map(p => [p, hash(p)]));
    const messages = [{ role: 'user', content: process.env.EVAL_TASK || '' }];
    for (let round = 1; round <= MAX_ROUNDS; round++) {
      result.rounds = round;
      const r = await post('/v1/chat/completions', { model: 'eval', messages, tools: TOOLS });
      const msg = r.choices[0].message;
      const calls = msg.tool_calls || [];
      if (!calls.length) { result.final = msg.content || ''; break; }
      messages.push({ role: 'assistant', content: msg.content || null, tool_calls: calls });
      for (const c of calls) {
        let args = {};
        try { args = JSON.parse(c.function.arguments || '{}'); } catch { /* argumentos inválidos: a ferramenta reclama */ }
        result.tool_calls.push(c.function.name + (args.command ? `(${String(args.command).slice(0, 80)})` : args.path ? `(${args.path})` : ''));
        messages.push({ role: 'tool', tool_call_id: c.id, content: runTool(c.function.name, args) });
      }
      if (round === MAX_ROUNDS) result.error = `limite de ${MAX_ROUNDS} rodadas atingido sem resposta final`;
    }
    const check = sh(process.env.EVAL_CHECK || 'true', 300000);
    result.check_exit = check.code;
    result.check_output = check.out.slice(-3000);
    result.protected_changed = protectedFiles.filter(p => hash(p) !== (before[p] ?? hash(p)));
    const now = walk(WORK);
    result.changed_files = [...new Set([...now, ...Object.keys(files)])].filter(p => hash(p) !== (before[p] ?? null));
  } catch (e) {
    result.error = String(e && e.message || e);
  }
  try { await post('/result', result); } catch (e) { console.error('não consegui entregar o resultado:', e.message); process.exitCode = 1; }
  console.log('EVAL_RESULT ' + JSON.stringify({ ...result, check_output: result.check_output.slice(-500) }));
})();
