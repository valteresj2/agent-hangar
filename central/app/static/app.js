const $ = (s, r = document) => r.querySelector(s);
const main = $('#main');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = n => n == null ? '—' : Number(n).toLocaleString('pt-BR');
const ago = iso => {
  if (!iso) return '—';
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return 'agora';
  if (s < 3600) return Math.floor(s / 60) + ' min';
  if (s < 86400) return Math.floor(s / 3600) + ' h';
  return Math.floor(s / 86400) + ' d';
};
const STATUS = {
  draft: ['Rascunho', ''], tested: ['Testado', 'info'], test_failed: ['Teste falhou', 'bad'],
  stage: ['Stage', 'warn'], production: ['Produção', 'ok'],
  running: ['Rodando', 'ok'], failed: ['Falhou', 'bad'], stopped: ['Parado', ''], replaced: ['Substituído', ''],
  exited: ['Caiu', 'bad'], missing: ['Ausente', 'bad'], starting: ['Iniciando', 'warn'], passed: ['Aprovado', 'ok'],
};
const pill = s => { const [t, c] = STATUS[s] || [s, '']; return `<span class="pill ${c}">${esc(t)}</span>`; };
const kindPill = k => k === 'multi' ? '<span class="pill info">multiagente</span>' : '<span class="pill">agente</span>';
const harnessPill = h => h ? `<span class="pill warn">harness:${esc(h.id)}</span>` : '';

function toast(msg, bad) {
  const d = document.createElement('div'); d.textContent = msg; if (bad) d.className = 'bad';
  $('#toast').append(d); setTimeout(() => d.remove(), bad ? 8000 : 3500);
}
const TK = 'hangar_token';
const store = { get: () => { try { return localStorage.getItem(TK); } catch { return null; } },
  set: v => { try { localStorage.setItem(TK, v); } catch { /* sem storage: pede de novo */ } },
  del: () => { try { localStorage.removeItem(TK); } catch { /* idem */ } } };
function token() {
  let t = store.get();
  if (!t) { t = (prompt('Token de admin (ADMIN_TOKEN) ou chave de API com escopo admin (ah_…):') || '').trim(); store.set(t); }
  return t;
}
$('#logout').onclick = () => { store.del(); location.reload(); };
const authHeaders = () => ({ 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' });

async function api(path, opts = {}) {
  const r = await fetch('/api' + path, {
    method: opts.method || 'GET', headers: authHeaders(),
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 401) { store.del(); throw new Error('Credencial inválida — recarregue a página para informar outra'); }
  if (r.status === 403) throw new Error('Esta chave não tem escopo admin');
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
  return data;
}
const usd = v => v == null ? '—' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: v && v < 0.01 ? 4 : 2 });
async function act(btn, fn, okMsg) {
  const old = btn.textContent; btn.disabled = true; btn.textContent = '…';
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = old; }
}

/* ---------- componentes ---------- */
function bars(series, key = 'requests') {
  const max = Math.max(1, ...series.map(s => s[key]));
  return `<div class="bars">${series.map(s => {
    const h = Math.round(100 * s[key] / max);
    return `<div class="b ${s.errors ? 'err' : ''}" style="height:${h}%" title="${s.day}: ${fmt(s[key])} ${key}${s.errors ? ' · ' + s.errors + ' erros' : ''}"></div>`;
  }).join('')}</div><div class="bars-x">${series.map(s => `<span>${s.day.slice(8)}</span>`).join('')}</div>`;
}
function hlist(obj) {
  const e = Object.entries(obj).sort((a, b) => b[1] - a[1]); const max = Math.max(1, ...e.map(x => x[1]));
  if (!e.length) return '<div class="mute small">Sem dados ainda</div>';
  return e.map(([k, v]) => `<div class="small"><div class="row between"><span>${esc(k)}</span><b>${fmt(v)}</b></div><div class="hbar"><i style="width:${100 * v / max}%"></i></div></div>`).join('<div style="height:8px"></div>');
}
const kpi = (v, l) => `<div class="card kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`;
const copyable = t => `<code class="inline copy" onclick="navigator.clipboard.writeText(this.textContent);toast('Copiado')">${esc(t)}</code>`;
window.toast = toast;

/* ---------- páginas ---------- */
async function dashboard() {
  const o = await api('/overview');
  const st = o.status;
  main.innerHTML = `
  <h1>Dashboard</h1><div class="sub">Visão geral da plataforma de agentes</div>
  <div class="grid g4">
    ${kpi(fmt(o.agents_total), 'Agentes registrados')}
    ${kpi(fmt(o.running_prod), 'Rodando em produção')}
    ${kpi(fmt(o.running_stage), 'Rodando em stage')}
    ${kpi(fmt(o.multi_agents), 'Multiagentes')}
    ${kpi(o.tests_pass_rate == null ? '—' : o.tests_pass_rate + '%', `Testes aprovados (${fmt(o.tests_total)} execuções)`)}
    ${kpi(fmt(o.requests_24h), 'Requisições 24h')}
    ${kpi(fmt(o.tokens_24h), 'Tokens 24h')}
    ${kpi(o.avg_latency_ms + ' ms', `Latência média · ${o.error_rate}% erros`)}
    ${kpi(usd(o.cost_24h), 'Custo 24h')}
    ${kpi(usd(o.cost_14d), 'Custo 14 dias')}
  </div>
  ${o.agents_total ? '' : `<div class="card mt hero"><h2>Comece por aqui</h2><div>Conecte o MCP do hangar no Claude, ChatGPT, Codex ou OpenCode e peça <i>“crie um agente que…”</i> — ou use um <a href="#/templates">template pronto</a> / <a href="#/agents/new">crie pela UI</a>.</div></div>`}
  <div class="grid g2 mt">
    <div class="card"><h2>Requisições por dia (14d)</h2>${bars(o.series)}</div>
    <div class="card"><h2>Custo por dia (14d, US$)</h2>${bars(o.series, 'cost_usd')}</div>
  </div>
  <div class="grid g2 mt">
    <div class="card"><h2>Agentes mais usados</h2>${o.top_agents.length ? `<table><tr><th>Agente</th><th>Req.</th><th>Tokens</th><th>Custo</th><th>Lat.</th><th>Erros</th></tr>${o.top_agents.map(a =>
      `<tr class="click" onclick="location.hash='#/agents/${a.slug}'"><td>${esc(a.name)}</td><td>${fmt(a.requests)}</td><td>${fmt(a.tokens)}</td><td>${usd(a.cost_usd)}</td><td>${a.avg_latency_ms}ms</td><td>${a.errors}</td></tr>`).join('')}</table>` : '<div class="empty">Ainda sem uso</div>'}</div>
    <div class="card"><h2>Pipeline de agentes</h2>
      ${['draft', 'test_failed', 'tested', 'stage', 'production'].map(k => `<div class="row between" style="margin-bottom:6px">${pill(k)}<b>${st[k] || 0}</b></div>`).join('')}
      <h3>Por canal</h3>${hlist(o.by_channel)}<h3>Por protocolo</h3>${hlist(o.by_protocol)}</div>
  </div>`;
}

async function agentsPage() {
  const list = await api('/agents');
  const render = q => {
    const rows = list.filter(a => (a.name + a.slug + a.objective).toLowerCase().includes(q.toLowerCase()));
    $('#rows').innerHTML = rows.length ? rows.map(a => `
      <tr class="click" onclick="location.hash='#/agents/${a.slug}'">
        <td><b>${esc(a.name)}</b><div class="mute small">${esc(a.objective).slice(0, 90)}</div></td>
        <td>${kindPill(a.kind)} ${harnessPill(a.harness)}</td><td>${pill(a.status)}</td><td>v${a.version}</td>
        <td><span class="dot ${a.stage ? 'on' : ''}"></span>stage &nbsp;<span class="dot ${a.prod ? 'on' : ''}"></span>prod</td>
        <td>${a.last_test ? pill(a.last_test.status) : '<span class="mute">—</span>'}</td>
        <td>${fmt(a.requests_7d)}</td><td>${usd(a.cost_7d)}</td><td class="mute">${esc(a.model)}</td></tr>`).join('') : '<tr><td colspan="9" class="empty">Nenhum agente. Peça no chat (Claude/ChatGPT/Codex) conectado ao MCP do hangar, use um <a href="#/templates">template</a> ou clique em “Novo agente”.</td></tr>';
  };
  main.innerHTML = `<div class="row between"><div><h1>Agentes</h1><div class="sub">${list.length} registrados</div></div>
    <div class="row"><input id="q" placeholder="Buscar…" style="max-width:260px"><a href="#/agents/new"><button>+ Novo agente</button></a></div></div>
    <div class="card scroll"><table><tr><th>Agente</th><th>Tipo</th><th>Status</th><th>Versão</th><th>Ambientes</th><th>Último teste</th><th>Req. 7d</th><th>Custo 7d</th><th>Modelo</th></tr><tbody id="rows"></tbody></table></div>`;
  render(''); $('#q').oninput = e => render(e.target.value);
}

async function newAgentPage() {
  const c = await api('/catalog');
  const conns = c.llm_connections;
  const opt = (list, empty) => `<option value="">${empty}</option>` + list.map(x => `<option value="${esc(x.name)}">${esc(x.name)} · ${esc(x.protocol)} · ${esc(x.model_name)}</option>`).join('');
  main.innerHTML = `<a href="#/agents" class="mute small">← Agentes</a><h1>Novo agente</h1>
  <div class="sub">O jeito principal é pedir pelo chat (MCP) — este formulário cobre o básico; depois refine na aba <b>Spec</b>.</div>
  <div class="card"><div class="grid g2">
    <label>Nome<input id="na-name" placeholder="ex.: Triagem de chamados"></label>
    <label>Responsável<input id="na-owner" placeholder="time ou pessoa (opcional)"></label></div>
    <label class="mt">Objetivo<input id="na-obj" placeholder="o que o agente faz"></label>
    <label class="mt">Saída final<input id="na-out" placeholder="o que ele entrega"></label>
    <label class="mt">Instruções<textarea id="na-ins" rows="5" placeholder="como ele deve se comportar"></textarea></label>
    <div class="grid g2 mt">
      <label>Tipo<select id="na-kind"><option value="chat">Agente de chat (LLM + tools/MCP)</option>
        <option value="claude-code">Harness claude-code</option><option value="codex">Harness codex</option>
        <option value="hermes">Harness hermes</option><option value="deepseek-harness">Harness deepseek-harness</option></select></label>
      <label>Conexão de LLM<select id="na-conn">${opt(conns, 'nenhuma (mock — só para testar o fluxo)')}</select></label></div>
    <div class="row mt"><button id="na-go">Criar</button><label class="row small"><input type="checkbox" id="na-ship" style="width:auto"> testar e shipar em seguida</label></div></div>`;
  $('#na-go').onclick = e => act(e.target, async () => {
    const body = { name: $('#na-name').value.trim(), objective: $('#na-obj').value.trim(), final_output: $('#na-out').value.trim(), owner: $('#na-owner').value.trim() };
    if (!body.name || !body.objective || !body.final_output) throw new Error('Nome, objetivo e saída final são obrigatórios');
    const a = await api('/agents', { method: 'POST', body });
    const kind = $('#na-kind').value, conn = $('#na-conn').value;
    const patch = { instructions: $('#na-ins').value };
    if (kind === 'chat') { if (conn) patch.llm = { connection: conn }; } else patch.harness = { id: kind, ...(conn ? { connection: conn } : {}) };
    await api('/agents/' + a.slug, { method: 'PATCH', body: patch });
    if ($('#na-ship').checked) { await api(`/agents/${a.slug}/ship`, { method: 'POST' }); toast('Agente em produção'); }
    location.hash = '#/agents/' + a.slug;
  }, 'Agente criado');
}

async function agentDetail(slug, tab = 'overview') {
  const a = await api('/agents/' + slug);
  const tabs = ['overview', 'connect', 'topology', 'spec', 'versions', 'tests', 'jobs', 'deployments', 'usage', 'playground'];
  const names = { overview: 'Visão geral', connect: 'Conectar', topology: 'Multiagente', spec: 'Spec', versions: 'Versões', tests: 'Testes', jobs: 'Jobs', deployments: 'Deployments', usage: 'Uso', playground: 'Playground' };
  const shown = tabs.filter(t => (t !== 'topology' || a.kind === 'multi') && (t !== 'jobs' || a.harness));
  main.innerHTML = `
  <div class="row between"><div><a href="#/agents" class="mute small">← Agentes</a>
    <h1>${esc(a.name)} ${kindPill(a.kind)} ${harnessPill(a.harness)} ${pill(a.status)}</h1><div class="sub">${esc(a.objective)}</div></div>
    <div class="row">
      <button id="b-test" class="ghost">Rodar testes</button>
      <button id="b-stage" class="ghost">Deploy stage</button>
      <button id="b-ship">Shipar → produção</button>
      <button id="b-stop" class="ghost">Parar prod</button>
      <button id="b-del" class="danger">Excluir</button>
    </div></div>
  <div class="tabs">${shown.map(t => `<a href="#/agents/${slug}/${t}" class="${t === tab ? 'on' : ''}">${names[t]}</a>`).join('')}</div>
  <div id="tab"></div>`;
  const reload = () => route();
  $('#b-test').onclick = e => act(e.target, () => api(`/agents/${slug}/test`, { method: 'POST' }).then(r => { toast(`Testes: ${r.summary}`, r.status !== 'passed'); reload(); }));
  $('#b-stage').onclick = e => act(e.target, () => api(`/agents/${slug}/deploy`, { method: 'POST', body: { env: 'stage' } }).then(reload), 'Deploy em stage concluído');
  $('#b-ship').onclick = e => act(e.target, () => api(`/agents/${slug}/ship`, { method: 'POST' }).then(reload), 'Agente em produção');
  $('#b-stop').onclick = e => act(e.target, () => api(`/agents/${slug}/stop`, { method: 'POST', body: { env: 'prod' } }).then(reload), 'Produção parada');
  $('#b-del').onclick = e => confirm(`Excluir ${a.name} e seus containers?`) && act(e.target, () => api('/agents/' + slug, { method: 'DELETE' }).then(() => location.hash = '#/agents'));
  const t = $('#tab');
  ({ overview, connect: agentConnect, topology, spec: specEditor, versions, tests, jobs, deployments, usage, playground })[tabs.includes(tab) ? tab : 'overview'](t, a);
}

async function agentConnect(t, a) {
  const [clients, conns] = await Promise.all([api('/connect/clients'), api(`/agents/${a.slug}/connections`)]);
  const modeLabel = { mcp: '🔌 Como ferramenta (MCP)', model: '💬 Como modelo' };
  const warn = a.prod ? '' : `<div class="card warn-card">Este agente ainda não está em <b>produção</b>: as conexões apontam para <code>/gw/${esc(a.slug)}</code> e só respondem depois do ship.</div>`;
  t.innerHTML = `${warn}
  <div class="card"><h2>Conectar a ferramentas — plug and play, opcional por ferramenta</h2>
    <div class="mute small"><b>MCP</b>: o agente vira uma <i>ferramenta</i> que o LLM da ferramenta chama (todas as plataformas).
    <b>Modelo</b>: o agente vira um <i>modelo</i> no seletor do chat e conduz a conversa — recebe anexos e usa as próprias tools (LibreChat, Open WebUI, OpenCode, SDKs).
    Cada conexão gera uma chave só desta ferramenta e deste agente: revogue quando quiser, sem afetar as outras; o uso aparece por ferramenta.</div></div>
  <div id="cn-list"></div>
  <div id="cn-out"></div>
  <div class="grid g3 mt">${clients.map(c => `<div class="card"><h2>${esc(c.label)}</h2><div class="mute small">${esc(c.note)}</div>
    <div class="row mt">${c.modes.map(m => `<button class="${m === c.modes[0] ? '' : 'ghost'} cn-go" data-c="${c.id}" data-m="${m}">${modeLabel[m]}</button>`).join('')}</div></div>`).join('')}</div>`;
  const drawList = list => {
    $('#cn-list').innerHTML = `<div class="card mt"><h2>Conexões ativas (${list.length})</h2>
    ${list.length ? `<div class="scroll"><table><tr><th>Ferramenta</th><th>Modo</th><th>Chave</th><th>Criada</th><th>Último uso</th><th></th></tr>
    ${list.map(k => `<tr><td><b>${esc(k.client_label)}</b></td><td>${esc(modeLabel[k.mode] || k.mode)}</td><td><code class="inline">${esc(k.prefix)}…</code></td>
      <td class="mute">${ago(k.created_at)}</td><td class="mute">${k.last_used_at ? ago(k.last_used_at) + ' atrás' : 'nunca'}</td>
      <td><button class="ghost cn-rev" data-id="${k.id}" data-n="${esc(k.client_label)}">Desconectar</button></td></tr>`).join('')}</table></div>`
      : '<div class="mute">Nenhuma ainda — escolha uma ferramenta abaixo.</div>'}</div>`;
    $('#cn-list').querySelectorAll('.cn-rev').forEach(b => b.onclick = e => confirm(`Desconectar ${b.dataset.n}? Essa ferramenta perde o acesso ao agente.`) &&
      act(e.target, async () => drawList(await api('/keys/' + b.dataset.id, { method: 'DELETE' }).then(() => api(`/agents/${a.slug}/connections`))), 'Desconectado'));
  };
  drawList(conns);
  t.querySelectorAll('.cn-go').forEach(b => b.onclick = e => act(e.target, async () => {
    const r = await api(`/agents/${a.slug}/connections`, { method: 'POST', body: { client: b.dataset.c, mode: b.dataset.m } });
    const label = clients.find(c => c.id === b.dataset.c).label;
    $('#cn-out').innerHTML = `<div class="card mt warn-card"><div class="row between"><h2>${esc(label)} — ${esc(modeLabel[b.dataset.m])}</h2>
      <button class="ghost" id="cn-copy">Copiar</button></div>
      <ol class="small">${r.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ol>
      ${r.file ? `<div class="small mute">Arquivo: <code>${esc(r.file)}</code></div>` : ''}
      <pre id="cn-code">${esc(r.content)}</pre>
      <div class="small"><b>A chave aparece só agora.</b> Para desligar, use “Desconectar” acima (só esta ferramenta perde o acesso).</div></div>`;
    $('#cn-copy').onclick = () => { navigator.clipboard.writeText(r.content); toast('Configuração copiada'); };
    $('#cn-out').scrollIntoView({ behavior: 'smooth' });
    const list = await api(`/agents/${a.slug}/connections`);
    drawList(list);
    toast(`Conexão criada (${list.length} ativa(s))`);
  }));
}

function specEditor(t, a) {
  t.innerHTML = `<div class="card"><div class="row between"><h2>Spec (v${a.version})</h2>
      <div class="row"><a class="small" href="/api/spec/schema" target="_blank" id="schema-link">JSON Schema</a><button id="sp-save">Salvar como nova versão</button></div></div>
    <div class="mute small">Substitui a spec inteira (PUT). Validação no servidor: campos desconhecidos ou combinações inválidas (ex.: <code>llm.connection</code> + <code>harness</code>) são recusados com a mensagem do erro. Salvar sem mudanças não cria versão.</div>
    <textarea id="sp-json" class="mt code" rows="24" spellcheck="false">${esc(JSON.stringify(a.spec, null, 2))}</textarea>
    <div id="sp-err" class="bad-text small mt"></div></div>`;
  $('#schema-link').onclick = async e => { e.preventDefault(); const w = window.open(); w.document.body.innerHTML = `<pre>${esc(JSON.stringify(await api('/spec/schema'), null, 2))}</pre>`; };
  $('#sp-save').onclick = e => act(e.target, async () => {
    let spec;
    try { spec = JSON.parse($('#sp-json').value); } catch (err) { $('#sp-err').textContent = 'JSON inválido: ' + err.message; throw err; }
    $('#sp-err').textContent = '';
    try { const r = await api(`/agents/${a.slug}/spec`, { method: 'PUT', body: spec }); toast(r.version === a.version ? 'Sem mudanças' : `Salvo como v${r.version}`); route(); }
    catch (err) { $('#sp-err').textContent = err.message; throw err; }
  });
}

function overview(t, a) {
  const s = a.spec;
  const list = (arr, f = x => x) => arr.length ? arr.map(x => `<span class="chip">${esc(f(x))}</span>`).join('') : '<span class="mute">nenhum</span>';
  const compositionCard = a.harness ? `
    <div class="card"><h2>Composição</h2><dl class="kv">
      <dt>Tipo</dt><dd><span class="pill info">agente com harness</span></dd>
      <dt>Harness</dt><dd><span class="chip">${esc(s.harness.id)}</span></dd>
      <dt>Conexão LLM</dt><dd>${s.harness.connection ? `<span class="chip">${esc(s.harness.connection)}</span>` : '<span class="mute">nenhuma (modo mock)</span>'}</dd>
      ${s.harness.stage ? `<dt>Override stage</dt><dd><code class="inline">${esc(JSON.stringify(s.harness.stage))}</code></dd>` : ''}
      ${s.harness.prod ? `<dt>Override prod</dt><dd><code class="inline">${esc(JSON.stringify(s.harness.prod))}</code></dd>` : ''}
      <dt>Skills</dt><dd>${list(s.skills, x => x.name || x)}</dd><dt>MCPs</dt><dd>${list(s.mcps, x => x.name || x)}</dd>
      <dt>Casos de teste</dt><dd>${s.tests.length}</dd></dl>
      <div class="mute small mt">Cada chamada sobe um container Docker efêmero, roda a tarefa e é destruída — nunca fica um container ocioso.</div></div>`
    : `
    <div class="card"><h2>Composição</h2><dl class="kv">
      <dt>Conexão LLM</dt><dd>${s.llm.connection ? `<span class="chip">${esc(s.llm.connection)}</span>` : '<span class="mute">nenhuma (mock/echo)</span>'}</dd>
      <dt>Modelo</dt><dd>${esc(s.llm.model) || '<span class="mute">padrão da conexão</span>'} <span class="mute">· temp ${s.llm.temperature ?? 0.2}</span></dd>
      ${s.llm.stage ? `<dt>Override stage</dt><dd><code class="inline">${esc(JSON.stringify(s.llm.stage))}</code></dd>` : ''}
      ${s.llm.prod ? `<dt>Override prod</dt><dd><code class="inline">${esc(JSON.stringify(s.llm.prod))}</code></dd>` : ''}
      <dt>Skills</dt><dd>${list(s.skills, x => x.name || x)}</dd><dt>MCPs</dt><dd>${list(s.mcps, x => x.name || x)}</dd>
      <dt>Tools</dt><dd>${list(s.tools, x => x.name)}</dd><dt>Sub-agentes</dt><dd>${list(s.sub_agents)}</dd>
      <dt>Canais</dt><dd>${list(s.channels)}</dd><dt>Casos de teste</dt><dd>${s.tests.length}</dd></dl></div>`;
  t.innerHTML = `<div class="grid g2">
    <div class="card"><h2>Registro</h2><dl class="kv">
      <dt>Slug</dt><dd>${copyable(a.slug)}</dd><dt>Saída final</dt><dd>${esc(a.final_output)}</dd>
      <dt>Responsável</dt><dd>${esc(a.owner) || '—'}</dd><dt>Versão atual</dt><dd>v${a.version}</dd>
      <dt>Criado</dt><dd>${ago(a.created_at)} atrás</dd><dt>Atualizado</dt><dd>${ago(a.updated_at)} atrás</dd></dl></div>
    ${compositionCard}
    <div class="card"><h2>Instruções</h2><pre>${esc(s.instructions) || '(sem instruções)'}</pre></div>
    <div class="card"><h2>Endpoints (produção)</h2><div class="mute small">Header <code>Authorization: Bearer &lt;chave invoke&gt;</code> (gere em <a href="#/keys">Chaves de API</a>); opcional <code>X-Channel: slack</code> para métricas por canal.
      ${a.harness ? ' Agente com harness: cada chamada (OpenAI, A2A, ACP ou MCP) vira um job num container efêmero.' : ''}</div>
      ${Object.entries(a.endpoints).map(([k, v]) => `<h3>${k}</h3>${copyable(v)}`).join('')}
      <h3>Stage</h3>${copyable(a.endpoints.openai.replace('/gw/', '/gw-stage/'))}</div></div>`;
}

async function topology(t, a) {
  const subs = await Promise.all(a.sub_agents.map(s => api('/agents/' + s)));
  t.innerHTML = `<div class="card"><h2>Orquestração</h2>
    <div class="card" style="border-color:var(--accent)"><b>${esc(a.name)}</b> ${pill(a.status)}<div class="mute small">Orquestrador · delega via A2A</div></div>
    <div style="border-left:2px solid var(--line);margin:0 0 0 24px;padding-left:20px">
    ${subs.map(s => `<div class="card mt" onclick="location.hash='#/agents/${s.slug}'" style="cursor:pointer"><b>${esc(s.name)}</b> ${pill(s.status)} ${s.prod ? '<span class="pill ok">prod ✓</span>' : ''}<div class="mute small">${esc(s.objective)}</div></div>`).join('')}</div></div>`;
}

function versions(t, a) {
  const tested = new Set(a.tests.filter(x => x.status === 'passed').map(x => x.version));
  t.innerHTML = [...a.versions].sort((x, y) => y.version - x.version).map(v => `<div class="card mt"><div class="row between"><b>v${v.version}${v.version === a.version ? ' <span class="pill ok">atual</span>' : ''}${tested.has(v.version) ? ' <span class="pill info">testada ✓</span>' : ''}</b>
    <span class="row"><span class="mute small">${esc(v.created_by)} · ${ago(v.created_at)} atrás</span>
    ${v.version !== a.version ? `<button class="ghost rb" data-v="${v.version}">Restaurar</button>` : ''}</span></div>
    <details><summary>Ver spec</summary><pre>${esc(JSON.stringify(v.spec, null, 2))}</pre></details></div>`).join('');
  t.querySelectorAll('.rb').forEach(b => b.onclick = e => confirm(`Restaurar a spec da v${b.dataset.v} como uma nova versão? (depois rode testes/ship)`) &&
    act(e.target, () => api(`/agents/${a.slug}/rollback`, { method: 'POST', body: { version: +b.dataset.v } }).then(route), 'Versão restaurada'));
}

function testCard(r) {
  return `<div class="card mt"><div class="row between"><div>${pill(r.status)} <b>v${r.version}</b> · ${esc(r.env)} · ${esc(r.summary)}</div>
    <span class="mute small">${ago(r.created_at)} atrás · ${r.duration_ms}ms</span></div>
    <table>${r.results.map(x => `<tr><td style="width:24px">${x.passed ? '✅' : '❌'}</td><td>${esc(x.name)}</td><td class="mute small">${esc(x.detail)}</td><td class="mute small">${x.latency_ms}ms</td></tr>`).join('')}</table></div>`;
}
function tests(t, a) {
  t.innerHTML = a.tests.length ? a.tests.map(testCard).join('') : '<div class="empty">Nenhum teste registrado. Clique em “Rodar testes”.</div>';
}

function jobCard(j) {
  return `<div class="card mt"><div class="row between"><div>${pill(j.status)} <b>#${j.id}</b> · v${j.version} · ${esc(j.env)} · ${esc(j.harness_id)}${j.connection ? ' · ' + esc(j.connection) : ' · mock'}</div>
    <span class="mute small">${ago(j.created_at)} atrás · ${fmt(j.duration_ms)}ms · ${fmt((j.tokens_in || 0) + (j.tokens_out || 0))} tokens · ${usd(j.cost_usd)}</span></div>
    <div class="mt"><b>Tarefa:</b> ${esc(j.task)}</div>
    <div class="mt"><b>Resultado:</b><pre>${esc(j.result) || '(vazio)'}</pre></div>
    ${j.diff ? `<details class="mt"><summary>Diff</summary><pre>${esc(j.diff)}</pre></details>` : ''}
    ${j.logs ? `<details class="mt"><summary>Logs</summary><pre>${esc(j.logs)}</pre></details>` : ''}</div>`;
}
function jobs(t, a) {
  t.innerHTML = a.jobs.length ? a.jobs.map(jobCard).join('') : '<div class="empty">Nenhum job ainda. Use a aba Playground para disparar uma tarefa.</div>';
}

function depTable(list, withAgent) {
  return `<div class="card"><table><tr>${withAgent ? '<th>Agente</th>' : ''}<th>Ambiente</th><th>Versão</th><th>Status</th><th>Container</th><th>Endpoint</th><th>Quando</th></tr>
  ${list.map(d => `<tr>${withAgent ? `<td><a href="#/agents/${d.agent}">${esc(d.agent_name)}</a></td>` : ''}<td>${d.env}</td><td>v${d.version}</td><td>${pill(d.status)}${d.error ? `<details><summary>erro</summary><pre>${esc(d.error)}</pre></details>` : ''}</td>
  <td><code class="inline">${esc(d.container)}</code></td><td>${copyable(d.url)}</td><td class="mute">${ago(d.created_at)}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">Nenhum deployment</td></tr>'}</table></div>`;
}
async function deployments(t, a) {
  t.innerHTML = depTable(a.deployments) + `<div class="card mt"><div class="row between"><h2>Logs do container</h2>
    <div class="row"><select id="lenv" style="width:auto"><option>prod</option><option>stage</option></select><button id="lb" class="ghost">Carregar</button></div></div><pre id="logs">Clique em carregar.</pre></div>`;
  $('#lb').onclick = async () => { $('#logs').textContent = (await api(`/agents/${a.slug}/logs?env=${$('#lenv').value}`)).logs || '(vazio)'; };
}

function usage(t, a) {
  const u = a.usage;
  t.innerHTML = `<div class="grid g2"><div class="card"><h2>Requisições (14d)</h2>${bars(u.series)}</div><div class="card"><h2>Custo (14d, US$)</h2>${bars(u.series, 'cost_usd')}</div></div>
  <div class="card mt scroll"><h2>Últimas chamadas</h2><table><tr><th>Quando</th><th>Env</th><th>Canal</th><th>Protocolo</th><th>Tokens</th><th>Custo</th><th>Latência</th><th></th></tr>
  ${u.recent.map(r => `<tr><td>${ago(r.at)}</td><td>${r.env}</td><td>${esc(r.channel)}</td><td>${r.protocol}</td><td>${fmt(r.tokens)}</td><td>${usd(r.cost_usd)}</td><td>${r.latency_ms}ms</td><td>${r.ok ? '✅' : '❌'}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">Sem uso registrado</td></tr>'}</table></div>`;
}

function playground(t, a) {
  if (a.harness) return playgroundHarness(t, a);
  t.innerHTML = `<div class="card"><div class="row between"><h2>Playground</h2><select id="penv" style="width:auto"><option>prod</option><option>stage</option></select></div>
    <div id="chat" class="chat"></div><div class="row"><input id="pmsg" placeholder="Mensagem para o agente…" style="flex:1"><button id="psend">Enviar</button></div></div>`;
  const add = (c, x) => { const d = document.createElement('div'); d.className = 'msg ' + c; d.textContent = x; $('#chat').append(d); d.scrollIntoView(); return d; };
  const send = async () => {
    const m = $('#pmsg').value.trim(); if (!m) return; $('#pmsg').value = ''; add('u', m);
    const w = add('a', '…');
    try {
      const r = await api(`/agents/${a.slug}/chat`, { method: 'POST', body: { message: m, env: $('#penv').value } });
      const u = r.usage || {};
      w.textContent = r.reply + `\n\n${r.latency_ms}ms · ${fmt(u.total_tokens || (u.prompt_tokens || 0) + (u.completion_tokens || 0))} tokens · ${usd(u.cost_usd || 0)}` + ((r.trace || []).length ? ` · ${r.trace.length} tool call(s)` : '');
    } catch (e) { w.textContent = 'Erro: ' + e.message; }
  };
  $('#psend').onclick = send; $('#pmsg').onkeydown = e => e.key === 'Enter' && send();
}

function playgroundHarness(t, a) {
  t.innerHTML = `<div class="card"><div class="row between"><h2>Playground — job de harness</h2>
      <select id="penv" style="width:auto"><option>stage</option><option>prod</option></select></div>
    <div class="mute small">Cada execução sobe um container Docker isolado (${esc(a.spec.harness.id)}), roda a tarefa e é destruída. Pode levar até alguns minutos.</div>
    <textarea id="ptask" placeholder="Descreva a tarefa que o agente deve executar…" rows="3" class="mt"></textarea>
    <div class="row mt"><button id="prun">Rodar job</button><button id="pcancel" class="danger" hidden>Cancelar</button><span id="pstatus" class="mute small"></span></div>
    <pre id="plive" hidden></pre>
    <div id="pjobresult" class="mt"></div></div>`;
  let current = null;
  $('#pcancel').onclick = e => current && act(e.target, () => api(`/jobs/${current}/cancel`, { method: 'POST' }), 'Cancelamento enviado');
  $('#prun').onclick = e => act(e.target, async () => {
    const task = $('#ptask').value.trim();
    if (!task) throw new Error('Descreva a tarefa');
    $('#pjobresult').innerHTML = ''; $('#plive').textContent = ''; $('#plive').hidden = false;
    const j = await api(`/agents/${a.slug}/job`, { method: 'POST', body: { task, env: $('#penv').value, wait: false } });
    current = j.id; $('#pcancel').hidden = false; $('#pstatus').textContent = `job #${j.id}: ${j.status}`;
    try {
      await streamJob(j.id, ev => {
        if (ev.event === 'status') $('#pstatus').textContent = `job #${j.id}: ${ev.data.status}`;
        if (ev.event === 'log') { const p = $('#plive'); p.textContent += ev.data.text; p.scrollTop = p.scrollHeight; }
        if (ev.event === 'done') { $('#pjobresult').innerHTML = jobCard(ev.data); $('#plive').hidden = true; }
      });
    } finally { current = null; $('#pcancel').hidden = true; }
  });
}

/* SSE via fetch (EventSource não manda header Authorization) */
async function streamJob(id, onEvent) {
  const r = await fetch(`/api/jobs/${id}/events`, { headers: authHeaders() });
  if (!r.ok || !r.body) throw new Error('Falha ao acompanhar o job: ' + r.status);
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const ev = (chunk.match(/^event: (.*)$/m) || [])[1], data = (chunk.match(/^data: (.*)$/m) || [])[1];
      if (ev && data) onEvent({ event: ev, data: JSON.parse(data) });
    }
  }
}

async function deploymentsPage() {
  main.innerHTML = `<h1>Deployments</h1><div class="sub">Um container Docker isolado por agente e ambiente</div>` + depTable(await api('/deployments'), true);
}
async function testsPage() {
  const l = await api('/tests');
  main.innerHTML = `<h1>Testes</h1><div class="sub">Execuções em stage registradas por versão</div>` +
    (l.map(r => `<div class="mt"><a href="#/agents/${r.agent}"><b>${esc(r.agent_name)}</b></a>${testCard(r)}</div>`).join('') || '<div class="empty">Nenhum teste ainda</div>');
}
async function usagePage() {
  const [o, l] = await Promise.all([api('/overview'), api('/usage')]);
  main.innerHTML = `<h1>Uso e custo</h1><div class="sub">Chamadas de agentes e multiagentes por canal e protocolo · custo = tokens × preço da conexão (ou o que o harness reportou)</div>
  <div class="grid g4">${kpi(fmt(o.requests_24h), 'Requisições 24h')}${kpi(usd(o.cost_24h), 'Custo 24h')}${kpi(usd(o.cost_14d), 'Custo 14 dias')}${kpi(o.error_rate + '%', 'Erros 24h')}</div>
  <div class="grid g2 mt"><div class="card"><h2>Custo por dia (14d, US$)</h2>${bars(o.series, 'cost_usd')}</div><div class="card"><h2>Por canal</h2>${hlist(o.by_channel)}<h3>Por protocolo</h3>${hlist(o.by_protocol)}</div></div>
  <div class="card mt scroll"><h2>Últimas 100 chamadas</h2><table><tr><th>Quando</th><th>Agente</th><th>Env</th><th>Canal</th><th>Protocolo</th><th>Tokens</th><th>Custo</th><th>Latência</th><th></th></tr>
  ${l.map(r => `<tr><td>${ago(r.at)}</td><td><a href="#/agents/${r.agent}">${esc(r.agent)}</a></td><td>${r.env}</td><td>${esc(r.channel)}</td><td>${r.protocol}</td><td>${fmt(r.tokens)}</td><td>${usd(r.cost_usd)}</td><td>${r.latency_ms}ms</td><td>${r.ok ? '✅' : '❌'}</td></tr>`).join('') || '<tr><td colspan="9" class="empty">Sem uso ainda</td></tr>'}</table></div>`;
}
async function catalogPage() {
  const c = await api('/catalog');
  main.innerHTML = `<h1>Catálogo</h1><div class="sub">Skills, MCP servers e conexões de LLM reutilizáveis pelos agentes</div>
  <div class="card"><div class="row between"><h2>Conexões de LLM (${c.llm_connections.length})</h2>
    <span class="mute small">Nenhum LLM roda em Docker aqui — cada conexão é uma URL externa (gateway LiteLLM da empresa, OpenRouter, OpenAI…) + model_name + api key virtual.</span></div>
    <div class="scroll"><table><tr><th>Nome</th><th>Protocolo</th><th>URL</th><th>Modelo padrão</th><th>Preço (US$/1M in · out)</th><th>Chave</th><th></th></tr>
    ${c.llm_connections.map(x => `<tr><td><b>${esc(x.name)}</b><div class="mute small">${esc(x.description)}</div></td><td>${protoPill(x.protocol)}</td><td>${copyable(x.base_url)}</td><td>${esc(x.model_name)}</td>
      <td class="mute">${x.price_in_per_mtok == null && x.price_out_per_mtok == null ? '—' : `${x.price_in_per_mtok ?? 0} · ${x.price_out_per_mtok ?? 0}`}</td><td class="mute">${esc(x.api_key)}</td>
      <td><button class="ghost llm-del" data-n="${esc(x.name)}">Remover</button></td></tr>`).join('') || `<tr><td colspan="7" class="empty">Nenhuma — sem conexão, os agentes rodam em ${esc(c.fallback_model)}</td></tr>`}</table></div>
    <details class="mt"><summary>Adicionar / editar conexão (mesmo nome = edição; chave vazia mantém a atual)</summary><div class="grid g4 mt">
      <input id="lc-name" placeholder="nome (ex.: litellm-corp)"><input id="lc-url" placeholder="base_url (https://.../v1)">
      <input id="lc-model" placeholder="model_name (ex.: gpt-4o-mini)"><input id="lc-key" placeholder="api key virtual" type="password"></div>
      <div class="grid g4 mt"><select id="lc-protocol">${PROTO_OPTIONS('openai')}</select>
        <input id="lc-pin" type="number" step="0.01" min="0" placeholder="US$ por 1M tokens de entrada">
        <input id="lc-pout" type="number" step="0.01" min="0" placeholder="US$ por 1M tokens de saída"></div>
      <input id="lc-desc" placeholder="descrição (opcional)" class="mt"><button id="lc-add" class="mt">Salvar conexão</button></details></div>
  <div class="grid g2 mt"><div class="card"><h2>Skills (${c.skills.length})</h2>${c.skills.map(s => `<div class="mt"><b>${esc(s.name)}</b><div class="mute small">${esc(s.description)}</div><details><summary>conteúdo</summary><pre>${esc(s.content)}</pre></details></div>`).join('') || '<div class="mute">Nenhuma — registre pelo chat (<code>register_skill</code>) ou abaixo</div>'}
    <details class="mt"><summary>Adicionar skill</summary><input id="sk-name" placeholder="nome" class="mt"><input id="sk-desc" placeholder="descrição" class="mt"><textarea id="sk-content" placeholder="conteúdo (markdown)" rows="4" class="mt"></textarea><button id="sk-add" class="mt">Salvar skill</button></details></div>
  <div class="card"><h2>MCP servers (${c.mcp_servers.length})</h2>${c.mcp_servers.map(m => `<div class="mt"><b>${esc(m.name)}</b><div>${copyable(m.url)}</div><div class="mute small">${esc(m.description)}</div></div>`).join('') || '<div class="mute">Nenhum</div>'}
    <details class="mt"><summary>Adicionar MCP server</summary><input id="mc-name" placeholder="nome" class="mt"><input id="mc-url" placeholder="url (Streamable HTTP)" class="mt"><input id="mc-desc" placeholder="descrição" class="mt"><button id="mc-add" class="mt">Salvar MCP</button></details></div></div>`;
  $('#lc-add').onclick = e => act(e.target, () => api('/catalog/llm', { method: 'POST', body: {
    name: $('#lc-name').value.trim(), base_url: $('#lc-url').value.trim(),
    model_name: $('#lc-model').value.trim(), api_key: $('#lc-key').value, description: $('#lc-desc').value,
    protocol: $('#lc-protocol').value, price_in_per_mtok: num($('#lc-pin').value), price_out_per_mtok: num($('#lc-pout').value) } }).then(catalogPage), 'Conexão salva');
  document.querySelectorAll('.llm-del').forEach(b => b.onclick = e => confirm(`Remover a conexão "${b.dataset.n}"?`) &&
    act(e.target, () => api('/catalog/llm/' + encodeURIComponent(b.dataset.n), { method: 'DELETE' }).then(catalogPage), 'Removida'));
  $('#sk-add').onclick = e => act(e.target, () => api('/catalog/skills', { method: 'POST', body: {
    name: $('#sk-name').value.trim(), description: $('#sk-desc').value, content: $('#sk-content').value } }).then(catalogPage), 'Skill salva');
  $('#mc-add').onclick = e => act(e.target, () => api('/catalog/mcps', { method: 'POST', body: {
    name: $('#mc-name').value.trim(), url: $('#mc-url').value.trim(), description: $('#mc-desc').value } }).then(catalogPage), 'MCP salvo');
}
const num = v => v === '' || v == null ? null : Number(v);
const PROTOCOLS = {
  openai: 'openai — agente de chat, codex, hermes',
  anthropic: 'anthropic — harness claude-code',
  deepseek: 'deepseek — harness deepseek-harness',
};
const PROTO_OPTIONS = sel => Object.entries(PROTOCOLS).map(([k, v]) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${v}</option>`).join('');
const protoPill = p => p === 'anthropic' ? '<span class="pill info">anthropic</span>' : p === 'deepseek' ? '<span class="pill warn">deepseek</span>' : '<span class="pill">openai</span>';

/* ---------- Provedores: um cartão pronto por provedor de LLM conhecido ---------- */
const PROVIDERS = [
  { id: 'litellm', name: 'LiteLLM (gateway próprio)', protocol: 'openai',
    baseUrl: 'http://host.docker.internal:4000/v1',
    note: 'Seu próprio gateway. Use host.docker.internal (não "litellm") — o nome de serviço só resolve de dentro da rede Docker do projeto do LiteLLM, uma rede diferente desta. Alimenta agentes de chat e o harness codex; se seu LiteLLM expuser /v1/messages para um modelo Anthropic, dá pra registrar de novo aqui com protocolo anthropic para servir o harness claude-code.' },
  { id: 'openrouter', name: 'OpenRouter', protocol: 'openai', baseUrl: 'https://openrouter.ai/api/v1',
    note: 'Alimenta agentes de chat e o harness codex. Não serve o harness claude-code (só fala o protocolo da OpenAI, não o da Anthropic).' },
  { id: 'openai', name: 'OpenAI', protocol: 'openai', baseUrl: 'https://api.openai.com/v1',
    note: 'Alimenta agentes de chat e o harness codex (o caminho mais direto para o codex).' },
  { id: 'anthropic', name: 'Anthropic', protocol: 'anthropic', baseUrl: 'https://api.anthropic.com',
    note: 'Único protocolo que serve o harness claude-code de verdade.' },
  { id: 'deepseek', name: 'DeepSeek', protocol: 'deepseek', baseUrl: 'https://api.deepseek.com',
    note: 'API oficial da DeepSeek. Com protocolo deepseek serve o harness deepseek-harness; registre de novo com protocolo openai (base https://api.deepseek.com/v1) para agentes de chat.' },
  { id: 'gemini', name: 'Google Gemini', protocol: 'openai',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    note: 'Endpoint do Gemini compatível com OpenAI. Alimenta agentes de chat e o harness codex.' },
  { id: 'ollama', name: 'Ollama (modelo local)', protocol: 'openai',
    baseUrl: 'http://host.docker.internal:11434/v1',
    note: 'Modelo rodando na sua própria máquina, fora do Docker. A chave geralmente não é validada — pode deixar qualquer valor (ex.: "ollama").' },
  { id: 'custom', name: 'Outro / customizado', protocol: 'openai', baseUrl: '',
    note: 'Qualquer endpoint compatível com OpenAI (Bedrock, Vertex AI, Groq, Together, etc.) ou com a API da Anthropic — escolha o protocolo certo abaixo.' },
];

function providerCard(p) {
  return `<div class="card" id="pv-${p.id}"><h2>${esc(p.name)}</h2><div class="mute small">${esc(p.note)}</div>
    <div class="grid g4 mt">
      <input id="pv-${p.id}-name" placeholder="nome da conexão" value="${esc(p.id)}">
      <input id="pv-${p.id}-url" placeholder="base_url" value="${esc(p.baseUrl)}">
      <input id="pv-${p.id}-model" placeholder="model_name (ex.: gpt-4o-mini)">
      <input id="pv-${p.id}-key" placeholder="api key" type="password">
    </div>
    <div class="grid g4 mt">
      <select id="pv-${p.id}-protocol">${PROTO_OPTIONS(p.protocol)}</select>
      <input id="pv-${p.id}-pin" type="number" step="0.01" min="0" placeholder="US$/1M entrada (opcional)">
      <input id="pv-${p.id}-pout" type="number" step="0.01" min="0" placeholder="US$/1M saída (opcional)">
      <button id="pv-${p.id}-add">Salvar conexão</button>
    </div></div>`;
}

async function providersPage() {
  const c = await api('/catalog');
  main.innerHTML = `<h1>Provedores</h1><div class="sub">Adicione o(s) provedor(es) de LLM que você tem — a conexão fica disponível para qualquer agente ou harness via design_agent(llm=...) / design_agent(harness=...)</div>
  ${c.llm_connections.length ? `<div class="card"><h2>Já conectados (${c.llm_connections.length})</h2><table><tr><th>Nome</th><th>Protocolo</th><th>URL</th><th>Modelo</th></tr>
    ${c.llm_connections.map(x => `<tr><td><b>${esc(x.name)}</b></td><td>${protoPill(x.protocol)}</td><td class="mute small">${esc(x.base_url)}</td><td>${esc(x.model_name)}</td></tr>`).join('')}</table>
    <div class="mute small mt">Gerenciar (editar/remover) na aba <a href="#/catalog">Catálogo</a>.</div></div>` : ''}
  <div class="grid g2 mt">${PROVIDERS.map(providerCard).join('')}</div>`;
  PROVIDERS.forEach(p => {
    $(`#pv-${p.id}-add`).onclick = e => act(e.target, () => api('/catalog/llm', { method: 'POST', body: {
      name: $(`#pv-${p.id}-name`).value.trim(), base_url: $(`#pv-${p.id}-url`).value.trim(),
      model_name: $(`#pv-${p.id}-model`).value.trim(), api_key: $(`#pv-${p.id}-key`).value,
      protocol: $(`#pv-${p.id}-protocol`).value, description: `Provedor: ${p.name}`,
      price_in_per_mtok: num($(`#pv-${p.id}-pin`).value), price_out_per_mtok: num($(`#pv-${p.id}-pout`).value) } }).then(providersPage),
      `Conexão "${$(`#pv-${p.id}-name`).value.trim()}" salva`);
  });
}

async function connectPage() {
  const c = await api('/connect');
  const K = '<SUA_CHAVE>';
  const mcpName = 'agent-hangar';
  main.innerHTML = `<h1>Conectar clientes</h1><div class="sub">Conecte o MCP do hangar ao seu cliente e peça: “crie um agente que…”</div>
  <div class="card hero"><b>Conectar um agente pronto a uma ferramenta?</b> Abra o agente em <a href="#/agents">Agentes</a> → aba <b>Conectar</b>: escolha a ferramenta (Claude Code, Codex, OpenCode, Cursor, VS Code, LibreChat, Open WebUI…) e o modo (MCP ou modelo) e receba a configuração pronta, com uma chave só daquela ferramenta. Os exemplos abaixo são genéricos.</div>
  <div class="card warn-card mt"><b>Qual chave usar?</b> Para <b>construir</b> agentes (MCP do hangar) use uma chave com escopo <code>admin</code>.
    Para <b>consumir</b> um agente (LibreChat, Slack, OpenCode…) gere uma chave <code>invoke</code> restrita àquele agente em <a href="#/keys">Chaves de API</a> — nunca distribua o ADMIN_TOKEN.
    Nos exemplos, troque <code>${esc(K)}</code> pela chave.</div>
  <div class="grid mt">
  <div class="card"><h2>Claude Code (CLI)</h2><pre>claude mcp add --transport http ${mcpName} ${esc(c.mcp_url)} --header "Authorization: Bearer ${esc(K)}"</pre></div>
  <div class="card"><h2>Claude Desktop (claude_desktop_config.json)</h2><pre>${esc(JSON.stringify({ mcpServers: { [mcpName]: { command: 'npx', args: ['-y', 'mcp-remote', c.mcp_url, '--header', `Authorization: Bearer ${K}`, '--allow-http'] } } }, null, 2))}</pre></div>
  <div class="card"><h2>Codex CLI (~/.codex/config.toml)</h2><pre>[mcp_servers.${mcpName}]
url = "${esc(c.mcp_url)}"
http_headers = { Authorization = "Bearer ${esc(K)}" }</pre></div>
  <div class="card"><h2>OpenCode (opencode.json)</h2><pre>${esc(JSON.stringify({ mcp: { [mcpName]: { type: 'remote', url: c.mcp_url, headers: { Authorization: `Bearer ${K}` } } } }, null, 2))}</pre></div>
  <div class="card"><h2>ChatGPT / connectors</h2><div>Exige URL HTTPS pública. Publique o hangar atrás de um domínio/túnel e use <code>https://SEU-DOMINIO/mcp</code> como conector MCP.</div></div>
  <div class="card"><h2>Usar agentes já deployados</h2>
    <h3>LibreChat (librechat.yaml)</h3>
    <div class="mute small">Kit completo (Docker Compose, anexos, workspace por conversa, títulos baratos): <code>integrations/librechat</code> no repositório. De dentro de um container, troque <code>localhost</code> por <code>host.docker.internal</code>.</div>
    <pre>endpoints:
  custom:
    - name: "Agent Hangar"
      apiKey: "${esc(K)}"
      baseURL: "${esc(c.base_url)}/gw/&lt;slug&gt;/v1"
      models: { default: ["&lt;slug&gt;"], fetch: false }
      titleConvo: true
      titleEndpoint: "Hangar Titulos"      # títulos numa chamada curta, sem ferramentas
      headers:
        X-Channel: "librechat"
        X-Conversation-Id: "{{LIBRECHAT_BODY_CONVERSATIONID}}"   # 1 workspace/sessão por conversa
        X-User-Id: "{{LIBRECHAT_USER_ID}}"
    - name: "Hangar Titulos"
      apiKey: "${esc(K)}"
      baseURL: "${esc(c.base_url)}/gw/&lt;slug&gt;/v1"
      models: { default: ["&lt;slug&gt;"], fetch: false }
      titleConvo: false
      headers: { X-Hangar-Mode: "lite" }
fileConfig:
  endpoints:
    "Agent Hangar":                      # anexos chegam ao agente como arquivos
      supportedMimeTypes: ["^image/.*", "^text/.*", "^application/.*"]</pre>
    <h3>OpenAI-compatible (OpenCode, Open WebUI, SDKs)</h3><pre>base_url = ${esc(c.base_url)}/gw/&lt;slug&gt;/v1   model = &lt;slug&gt;   api_key = ${esc(K)}</pre>
    <h3>A2A</h3><pre>Agent Card: ${esc(c.base_url)}/gw/&lt;slug&gt;/.well-known/agent.json\nRPC: POST ${esc(c.base_url)}/gw/&lt;slug&gt;/a2a  (message/send)</pre>
    <h3>ACP</h3><pre>POST ${esc(c.base_url)}/gw/&lt;slug&gt;/acp/runs</pre>
    <h3>Slack / Teams</h3><div class="mute">Adaptadores nativos estão no roadmap. Hoje: aponte o bot para o endpoint OpenAI-compatible enviando <code>X-Channel: slack</code> para ver as métricas por canal.</div></div>
  <div class="card"><h2>Agente como ferramenta MCP (Claude Desktop/Code, OpenCode…)</h2>
    <div class="mute small">Cada agente deployado é também o seu próprio servidor MCP, com 1 tool (o nome do agente) — as skills, MCPs e tools configurados nele continuam ativos por trás da chamada.</div>
    <h3>Claude Code (CLI)</h3><pre>claude mcp add --transport http &lt;slug&gt; ${esc(c.base_url)}/gw/&lt;slug&gt;/mcp --header "Authorization: Bearer ${esc(K)}"</pre>
    <h3>Codex CLI</h3><pre>[mcp_servers.&lt;slug&gt;]
url = "${esc(c.base_url)}/gw/&lt;slug&gt;/mcp"
http_headers = { Authorization = "Bearer ${esc(K)}" }</pre>
    <div class="mute small">Troque <code>&lt;slug&gt;</code> pelo slug do agente. Use <code>/gw-stage/</code> em vez de <code>/gw/</code> para testar contra a versão de stage.</div></div>
  <div class="card"><h2>CLI <code>hangar</code></h2><pre>pip install ./cli
hangar login ${esc(c.base_url)} --token ${esc(K)}
hangar agents ls
hangar apply -f agents.yaml
hangar ship &lt;slug&gt;</pre></div>
  </div>`;
}

async function keysPage() {
  const [keys, agents] = await Promise.all([api('/keys'), api('/agents')]);
  main.innerHTML = `<h1>Chaves de API</h1><div class="sub">Credenciais com escopo mínimo. <b>invoke</b>: só chama agentes pelo gateway (opcionalmente só alguns). <b>admin</b>: administra tudo (UI, API, MCP do hangar).</div>
  <div class="card"><h2>Nova chave</h2><div class="grid g4">
    <input id="k-name" placeholder="nome (ex.: librechat-vendas)">
    <select id="k-scope"><option value="invoke">invoke — consumir agentes</option><option value="admin">admin — administrar</option></select>
    <select id="k-agents" multiple size="4" title="Ctrl/Cmd+clique para vários; nenhum = todos">${agents.map(a => `<option value="${esc(a.slug)}">${esc(a.name)}</option>`).join('')}</select>
    <button id="k-go">Gerar chave</button></div>
    <div class="mute small mt">Agentes selecionados restringem uma chave <b>invoke</b>; sem seleção ela invoca todos. O valor da chave aparece uma única vez.</div>
    <div id="k-new"></div></div>
  <div class="card mt scroll"><table><tr><th>Nome</th><th>Prefixo</th><th>Escopo</th><th>Agentes</th><th>Criada</th><th>Último uso</th><th></th></tr>
  ${keys.map(k => `<tr class="${k.revoked ? 'mute' : ''}"><td><b>${esc(k.name)}</b><div class="small mute">por ${esc(k.created_by)}</div></td><td><code class="inline">${esc(k.prefix)}…</code></td>
    <td>${k.scopes.map(s => `<span class="pill ${s === 'admin' ? 'warn' : 'info'}">${esc(s)}</span>`).join(' ')}</td>
    <td>${k.scopes.includes('admin') ? '<span class="mute">todos</span>' : (k.agents.length ? k.agents.map(s => `<span class="chip">${esc(s)}</span>`).join('') : '<span class="mute">todos</span>')}</td>
    <td class="mute">${ago(k.created_at)}</td><td class="mute">${k.last_used_at ? ago(k.last_used_at) : 'nunca'}</td>
    <td>${k.revoked ? '<span class="pill bad">revogada</span>' : `<button class="ghost k-rev" data-id="${k.id}" data-n="${esc(k.name)}">Revogar</button>`}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">Nenhuma chave ainda</td></tr>'}</table></div>`;
  $('#k-go').onclick = e => act(e.target, async () => {
    const name = $('#k-name').value.trim(); if (!name) throw new Error('Dê um nome à chave');
    const scope = $('#k-scope').value;
    const agentsSel = scope === 'invoke' ? [...$('#k-agents').selectedOptions].map(o => o.value) : [];
    const r = await api('/keys', { method: 'POST', body: { name, scopes: [scope], agents: agentsSel } });
    $('#k-new').innerHTML = `<div class="card mt warn-card"><b>Copie agora — não será exibida de novo:</b>${copyable(r.key)}</div>`;
  });
  document.querySelectorAll('.k-rev').forEach(b => b.onclick = e => confirm(`Revogar a chave "${b.dataset.n}"? Clientes que a usam param de funcionar.`) &&
    act(e.target, () => api('/keys/' + b.dataset.id, { method: 'DELETE' }).then(keysPage), 'Chave revogada'));
}

async function templatesPage() {
  const [list, c] = await Promise.all([api('/templates'), api('/catalog')]);
  const conns = c.llm_connections;
  const opts = (p, empty) => `<option value="">${empty}</option>` + conns.filter(x => !p || x.protocol === p).map(x => `<option value="${esc(x.name)}">${esc(x.name)} · ${esc(x.model_name)}</option>`).join('');
  const HP = { 'claude-code': 'anthropic', codex: 'openai', hermes: 'openai', 'deepseek-harness': 'deepseek' };
  main.innerHTML = `<h1>Templates</h1><div class="sub">Agentes prontos para aplicar, testar e shipar. Sem conexão de LLM eles nascem em modo mock (bom para ver o fluxo).</div>
  <div class="grid g2">${list.map(t => `<div class="card tpl"><div class="row between"><h2>${esc(t.title)}</h2>${t.harness ? harnessPill({ id: t.harness }) : t.agents.length > 1 ? kindPill('multi') : kindPill('single')}</div>
    <div>${esc(t.description)}</div><div class="mt">${t.tags.map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div>
    <div class="mute small mt">Agentes: ${t.agents.map(esc).join(', ')}<br>Precisa de: ${esc(t.needs)}</div>
    <div class="grid g2 mt">${t.harness
      ? `<select id="tp-${t.id}-h">${opts(HP[t.harness], `conexão ${HP[t.harness]} (vazio = mock)`)}</select>`
      : `<select id="tp-${t.id}-c">${opts('openai', 'conexão openai (vazio = mock)')}</select>`}
      <div class="row"><button class="tp-go" data-id="${t.id}">Aplicar</button><button class="ghost tp-ship" data-id="${t.id}">Aplicar + shipar</button></div></div>
    <div id="tp-${t.id}-out"></div></div>`).join('') || '<div class="empty">Nenhum template em TEMPLATES_DIR</div>'}</div>`;
  const apply = async (id, ship) => {
    const h = $(`#tp-${id}-h`), cc = $(`#tp-${id}-c`);
    const out = await api(`/templates/${id}/apply`, { method: 'POST', body: { connection: cc ? cc.value : '', harness_connection: h ? h.value : '' } });
    const agentsOut = out.filter(x => x.kind === 'agent');
    if (ship) await api(`/agents/${agentsOut[agentsOut.length - 1].slug}/ship`, { method: 'POST' });
    $(`#tp-${id}-out`).innerHTML = `<div class="mt small">${agentsOut.map(x => `<a href="#/agents/${x.slug}">${esc(x.slug)}</a> <span class="mute">(${esc(x.action)}, v${x.version})</span>`).join(' · ')}</div>`;
  };
  document.querySelectorAll('.tp-go').forEach(b => b.onclick = e => act(e.target, () => apply(b.dataset.id, false), 'Template aplicado'));
  document.querySelectorAll('.tp-ship').forEach(b => b.onclick = e => act(e.target, () => apply(b.dataset.id, true), 'Template aplicado e em produção'));
}

async function auditPage() {
  const l = await api('/audit');
  main.innerHTML = `<h1>Auditoria</h1><div class="sub">Tudo que foi criado, alterado, testado e deployado</div><div class="card"><table><tr><th>Quando</th><th>Ator</th><th>Ação</th><th>Alvo</th><th>Detalhe</th></tr>
  ${l.map(r => `<tr><td class="mute">${ago(r.at)}</td><td>${esc(r.actor)}</td><td><code class="inline">${esc(r.action)}</code></td><td>${esc(r.target)}</td><td class="mute small">${esc(r.detail)}</td></tr>`).join('')}</table></div>`;
}

/* ---------- roteamento ---------- */
async function route() {
  const [, r = '', a, b] = location.hash.split('/');
  document.querySelectorAll('nav a').forEach(x => x.classList.toggle('on', x.dataset.r === r));
  try {
    if (r === 'agents' && a === 'new') await newAgentPage();
    else if (r === 'agents' && a) await agentDetail(a, b);
    else await ({ '': dashboard, agents: agentsPage, templates: templatesPage, keys: keysPage, deployments: deploymentsPage, tests: testsPage, usage: usagePage, catalog: catalogPage, providers: providersPage, connect: connectPage, audit: auditPage }[r] || dashboard)();
  } catch (e) { main.innerHTML = `<div class="card"><h2>Erro</h2>${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', route);
route();
// auto-refresh só em páginas de leitura (nunca em formulários, editor de spec ou playground)
const NO_REFRESH = ['new', 'playground', 'spec'];
setInterval(() => {
  const parts = location.hash.split('/');
  if (document.hidden || ['keys', 'templates', 'catalog', 'providers', 'connect'].includes(parts[1])) return;
  if (NO_REFRESH.includes(parts[2]) || NO_REFRESH.includes(parts[3]) || document.activeElement.matches('input,textarea,select')) return;
  route();
}, 15000);
fetch('/api/health').then(r => r.json()).then(h => { $('#ver').textContent = 'v' + h.version; }).catch(() => {});
