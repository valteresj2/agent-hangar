/* Digital employee: agentes com cargo, gestor, alçada e tarefas, com o humano no circuito.
   Portal (/app): o espaço do dono e do gestor — lista, contratação (a mesma conversa do modo self do MCP), página do
   funcionário e a caixa de Decisões. Console (/ui): a força de trabalho digital do admin — visão geral, parada geral,
   catálogo de ações e piso da empresa. Usa os helpers de app.js ($, api, esc, act, toast, kpi, usd, ago, ME…). */

const EMP_STATUS = { onboarding: ['Contratação', ''], probation: ['Em experiência', 'info'], active: ['Ativo', 'ok'],
  paused: ['Pausado', 'warn'], offboarded: ['Desligado', 'bad'] };
const TASK_STATUS = { draft: ['Rascunho', ''], new: ['Na fila', 'info'], in_progress: ['Trabalhando', 'info'],
  waiting_human: ['Aguardando decisão', 'warn'], done: ['Concluída', 'ok'], failed: ['Falhou', 'bad'],
  cancelled: ['Cancelada', ''], expired: ['Expirou', 'bad'] };
const ACTION_LABEL = { read: 'Ler e consultar', delegate: 'Delegar a outro agente', write_internal: 'Alterar dados internos',
  send_external: 'Enviar para fora', speak_for_company: 'Falar em nome da empresa', publish: 'Publicar',
  financial: 'Dinheiro', delete: 'Apagar', prod_change: 'Mudar produção' };
const MODE_LABEL = { auto: ['Sozinho', 'ok'], notify: ['Faz e avisa', 'info'], approve: ['Pede aprovação', 'warn'],
  approve_2: ['Duas aprovações', 'warn'], never: ['Nunca', 'bad'] };
const LEVEL_LABEL = { intern: 'Estagiário', junior: 'Júnior', pleno: 'Pleno', senior: 'Sênior' };
const KIND_LABEL = { approval: 'aprovação', question: 'pergunta', admission: 'admissão', notice: 'aviso' };
const CHANNELS = ['portal', 'mcp', 'schedule', 'webhook'];
const KPI_METRIC = { tasks_done: 'Tarefas concluídas (30 dias)', done_rate: '% concluídas com sucesso', on_time_rate: '% dentro do prazo',
  approved_unedited_rate: '% aprovadas sem edição', avg_decision_min: 'Tempo médio de decisão (min)', cost_per_task: 'Custo por tarefa (US$)',
  expired_decisions: 'Decisões expiradas (30 dias)' };
const EMP_WEEKDAYS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
const CRON_PRESETS = [['0 9 * * 1-5', 'Dias úteis às 9h'], ['0 9 * * 1', 'Toda segunda às 9h'], ['0 17 * * 5', 'Toda sexta às 17h'],
  ['0 8 1 * *', 'Dia 1 de cada mês às 8h'], ['0 */4 * * *', 'A cada 4 horas']];
const SOURCE_LABEL = { routine: 'rotina', webhook: 'webhook' };
const kpiVal = k => k.actual == null ? '—' : k.unit === 'US$' ? usd(k.actual) : `${fmt(k.actual)}${k.unit === '%' ? '%' : k.unit === 'min' ? ' min' : ''}`;
const kpiPill = k => k.ok === true ? '<span class="pill ok">no alvo</span>' : k.ok === false ? '<span class="pill warn">fora do alvo</span>'
  : `<span class="pill">${k.metric ? 'sem dados ainda' : 'não medida'}</span>`;
const pillOf = (map, k) => { const [t, c] = map[k] || [k, '']; return `<span class="pill ${c}">${esc(t)}</span>`; };
const empPill = s => pillOf(EMP_STATUS, s);
const taskPill = s => pillOf(TASK_STATUS, s);
const modePill = m => pillOf(MODE_LABEL, m);
const lines = v => String(v || '').split('\n').map(x => x.trim()).filter(Boolean);
const csv = v => String(v || '').split(',').map(x => x.trim()).filter(Boolean);
const jsonBlock = v => `<pre class="code small" data-noi18n style="white-space:pre-wrap;margin:6px 0">${esc(JSON.stringify(v, null, 2))}</pre>`;
/* a ação exata, legível: cada argumento numa linha, textos longos com as quebras de linha (o e-mail como será enviado) */
const payloadView = v => v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length
  ? `<dl class="kv dc-payload" data-noi18n>${Object.entries(v).map(([k, x]) => `<dt><code class="inline">${esc(k)}</code></dt>
      <dd style="white-space:pre-wrap">${esc(typeof x === 'string' ? x : JSON.stringify(x, null, 2))}</dd>`).join('')}</dl>`
  : jsonBlock(v);

/* ---------- lista ---------- */
async function employeesPage() {
  const list = await api('/employees');
  main.innerHTML = `<div class="row between"><div><h1>Digital employees (${list.length})</h1>
    <div class="sub">Agentes com cargo, gestor humano e alçada: recebem tarefas, trabalham em segundo plano e pedem a sua decisão no que for sensível.</div></div>
    <a href="#/employees/new"><button>+ Contratar</button></a></div>
  ${list.length ? `<div class="grid g3">${list.map(empCard).join('')}</div>`
    : `<div class="card empty"><h2>Nenhum Digital employee ainda</h2><div class="mute">Contrate o primeiro pela sua ferramenta de IA (modo self, pelo MCP) ou
      pelo formulário guiado — os dois fazem as mesmas perguntas e só contratam com o cargo completo.</div>
      <div class="mt"><a href="#/employees/new"><button>Contratar um Digital employee</button></a></div></div>`}`;
}

function empCard(e) {
  const t = e.tasks || {};
  const working = (t.new || 0) + (t.in_progress || 0);
  return `<div class="card agent-card">
    <div class="row between"><a href="#/employees/${esc(e.slug)}"><b>${esc(e.name)}</b></a>${empPill(e.status)}</div>
    <div class="small" data-noi18n>${esc(e.title)}</div>
    <div class="mute small one-line" data-noi18n title="${esc(e.mission)}">${esc(e.mission)}</div>
    <div class="row small mt" style="gap:6px;flex-wrap:wrap"><span class="chip">${icon('user')}${esc(e.manager || '—')}</span>
      <span class="pill">${esc(LEVEL_LABEL[e.autonomy_level] || e.autonomy_level)}</span>
      ${e.open_decisions ? `<span class="pill warn">${e.open_decisions} decisão(ões)</span>` : ''}</div>
    <div class="mute small mt">${working} na fila · ${t.waiting_human || 0} aguardando · ${t.done || 0} concluídas · ${usd(e.cost_30d)} em 30 dias</div></div>`;
}

/* ---------- contratação: MCP primeiro, formulário guiado como alternativa ---------- */
const HIRE_PROMPT = () => window.LANG === 'en'
  ? 'Use Agent Hangar to hire a Digital employee: <job title>, who <mission>. Ask me for anything that is missing before hiring.'
  : 'Use o Agent Hangar para contratar um Digital employee: <cargo>, que <missão>. Pergunte o que faltar antes de contratar.';

async function employeeHirePage() {
  const teams = ME.teams || [];
  main.innerHTML = `<a href="#/employees" class="mute small">← Digital employees</a><h1>Contratar um Digital employee</h1>
  <div class="sub">O cargo só é criado quando estiver completo: missão, responsabilidades, gestor, sistemas, alçada, canais e as tarefas do período de experiência.</div>
  <div class="card hero"><h2>${icon('chat')} Pela sua ferramenta de IA (modo self, recomendado)</h2>
    <div class="mute small">No Claude, ChatGPT, Codex ou Cursor conectados ao Hangar (MCP), peça a contratação. A IA chama <code class="inline">plan_employee</code>,
      faz as perguntas que faltarem (no máximo 4 por vez), mostra o resumo do cargo para você confirmar e só então chama <code class="inline">hire_employee</code>.</div>
    <div class="mt">${copyable(HIRE_PROMPT())}</div>
    <div class="small mt"><a href="#/connect">Conectar ferramenta →</a></div></div>
  <div class="card mt"><h2>Ou pelo formulário guiado</h2>
    <div class="mute small">Clique em <b>Verificar</b> a qualquer momento: o Hangar diz o que falta (com a pergunta) e o que dá para reaproveitar do catálogo.</div>
    <div class="grid g2 mt">
      <label>Cargo<input id="h-title" placeholder="ex.: Analista de renovações"></label>
      <label>Gestor (e-mail)<input id="h-manager" placeholder="quem aprova e recebe os relatórios"></label>
      <label style="grid-column:1/-1">Missão<input id="h-mission" placeholder="o resultado pelo qual ele responde"></label>
      <label>Responsabilidades (uma por linha, 3 ou mais)<textarea id="h-resp" rows="4"></textarea></label>
      <label>Sistemas e ferramentas (uma por linha)<textarea id="h-systems" rows="4" placeholder="ex.: CRM&#10;e-mail"></textarea></label>
      <label>Agentes do catálogo que ele usa (slugs, separados por vírgula)<input id="h-specialists" placeholder="opcional"></label>
      <label>Skills e MCPs (separados por vírgula)<input id="h-pieces" placeholder="ex.: skill:propostas, mcp:crm"></label>
      <label>Substitutos (e-mails, separados por vírgula)<input id="h-backups" placeholder="decidem quando o gestor não responde"></label>
      <label>Time<select id="h-team">${teams.map(t => `<option value="${esc(t.slug)}">${esc(t.name)}</option>`).join('')}</select></label>
      <label>Nível de autonomia<select id="h-level">${Object.entries(LEVEL_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
      <fieldset class="small"><legend>Canais de entrada</legend>${CHANNELS.map(c => `<label class="row" style="gap:6px"><input type="checkbox" class="h-ch" value="${c}" ${['portal', 'mcp'].includes(c) ? 'checked' : ''}>${c}</label>`).join('')}</fieldset>
    </div>
    <h3 class="mt">Período de experiência</h3>
    <div class="mute small">Tarefas reais do cargo, com o resultado esperado. Ele as faz em stage; quando terminar, o gestor aprova a admissão.</div>
    <div id="h-prob"></div><button class="ghost small" id="h-prob-add">+ tarefa</button>
    <h3 class="mt">Alçada</h3><div id="h-auth" class="mute small">Clique em Verificar para ver a alçada padrão do nível escolhido, já com o piso da empresa.</div>
    <label class="row mt" style="gap:6px"><input type="checkbox" id="h-accept"> Aceito a alçada padrão (posso mudar depois, na aba Alçada)</label>
    <details class="mt"><summary>Opcional: metas, relatórios e limites</summary><div class="grid g2 mt">
      <label>Metas (KPIs), uma por linha<textarea id="h-kpis" rows="3"></textarea></label>
      <label>Webhook dos relatórios (Slack ou Teams, se for a ferramenta da empresa)<input id="h-hook" placeholder="https://hooks…"></label>
      <label>Orçamento por tarefa (US$)<input id="h-budget" type="number" step="0.1" placeholder="1.00"></label>
      <label>Tempo limite por tarefa (min)<input id="h-limit" type="number" placeholder="30"></label>
      <label>Hora do relatório diário<input id="h-hour" type="number" min="0" max="23" placeholder="18"></label>
      <label>Horário de trabalho<input id="h-hours" placeholder="ex.: seg-sex 8h-18h"></label></div></details>
    <div id="h-out" class="mt"></div>
    <div class="row mt"><button class="ghost" id="h-plan">Verificar</button><button id="h-hire">Contratar</button></div></div>`;
  const prob = $('#h-prob');
  const addProb = () => prob.insertAdjacentHTML('beforeend', `<div class="grid g3 mt h-pt">
    <input class="pt-title" placeholder="Tarefa"><input class="pt-body" placeholder="O que fazer"><input class="pt-exp" placeholder="Resultado esperado"></div>`);
  for (let i = 0; i < 3; i++) addProb();
  $('#h-prob-add').onclick = addProb;
  const fields = () => {
    const pieces = csv($('#h-pieces').value);
    const num = id => $(id).value === '' ? null : Number($(id).value);
    return {
      title: $('#h-title').value.trim(), mission: $('#h-mission').value.trim(), manager: $('#h-manager').value.trim(),
      responsibilities: lines($('#h-resp').value), systems: lines($('#h-systems').value), specialists: csv($('#h-specialists').value),
      skills: pieces.filter(p => !p.startsWith('mcp:')).map(p => p.replace(/^skill:/, '')), mcps: pieces.filter(p => p.startsWith('mcp:')).map(p => p.slice(4)),
      backups: csv($('#h-backups').value), team: $('#h-team').value, autonomy_level: $('#h-level').value,
      channels: [...document.querySelectorAll('.h-ch:checked')].map(c => c.value), accept_default_authority: $('#h-accept').checked,
      probation_tasks: [...document.querySelectorAll('.h-pt')].map(r => ({ title: $('.pt-title', r).value.trim(), body: $('.pt-body', r).value.trim(), expected: $('.pt-exp', r).value.trim() }))
        .filter(t => t.title),
      kpis: lines($('#h-kpis').value).map(k => ({ name: k })), report_webhook: $('#h-hook').value.trim(), working_hours: $('#h-hours').value.trim(),
      task_budget_usd: num('#h-budget'), task_time_limit_min: num('#h-limit'), report_hour: num('#h-hour'),
    };
  };
  const showPlan = p => {
    $('#h-auth').innerHTML = `<table><tr><th>Tipo de ação</th><th>Modo</th><th>Piso da empresa</th></tr>${p.authority_default.map(r =>
      `<tr><td>${esc(ACTION_LABEL[r.action_type] || r.action_type)}</td><td>${modePill(r.mode)}</td><td>${r.floor ? modePill(r.floor) : '<span class="mute">—</span>'}</td></tr>`).join('')}</table>`;
    const reuse = p.reuse && (p.reuse.agents || []).length ? `<div class="mt small"><b>Dá para reaproveitar:</b> ${p.reuse.agents.map(a => `<code class="inline">${esc(a.slug)}</code>`).join(' ')}
      ${(p.reuse.skills || []).map(s => `<code class="inline">skill:${esc(s.slug || s.name || s)}</code>`).join(' ')}</div>` : '';
    $('#h-out').innerHTML = p.ready ? `<div class="card ok-card"><b>Tudo pronto para contratar.</b>${reuse}</div>`
      : `<div class="card warn-card"><b>Falta responder (${p.missing.length}):</b><ul>${p.missing.map(m => `<li data-noi18n>${esc(m.question)}</li>`).join('')}</ul>${reuse}</div>`;
  };
  $('#h-plan').onclick = e => act(e.target, () => api('/employees/plan', { method: 'POST', body: fields() }).then(showPlan));
  $('#h-hire').onclick = e => act(e.target, async () => {
    const r = await api('/employees', { method: 'POST', body: fields() });
    if (!r.created) return showPlan({ ...r, authority_default: (await api('/employees/plan', { method: 'POST', body: fields() })).authority_default });
    toast('Contratado — comece o período de experiência');
    location.hash = `#/employees/${r.employee.slug}`;
  });
}

/* ---------- página do Digital employee ---------- */
async function employeeDetail(slug, tab = 'overview') {
  const e = await api('/employees/' + slug);
  const tabs = { overview: 'Visão geral', tasks: 'Tarefas', routines: 'Rotinas', decisions: 'Decisões', authority: 'Alçada', probation: 'Experiência', reports: 'Relatórios', settings: 'Configurações' };
  if (!e.can_manage) delete tabs.settings;
  const key = tabs[tab] ? tab : 'overview';
  main.innerHTML = `<div class="row between"><div><a href="#/employees" class="mute small">← Digital employees</a>
    <h1>${esc(e.name)} ${empPill(e.status)}</h1><div class="sub" data-noi18n>${e.title !== e.name ? `${esc(e.title)} — ` : ''}${esc(e.mission)}</div>
    <div class="row small" style="margin:-10px 0 4px"><span class="chip">${icon('user')}${window.t('gestor')}: ${esc(e.manager || '—')}</span>
      <span class="chip">${esc(LEVEL_LABEL[e.autonomy_level] || e.autonomy_level)}</span><a href="#/agents/${esc(slug)}/guide" class="small">Guia do agente →</a></div></div>
    <div class="row">${e.can_manage ? `
      ${e.status === 'onboarding' ? '<button id="e-prob">Começar experiência</button>' : ''}
      ${['probation', 'active'].includes(e.status) ? '<button id="e-pause" class="danger">Pausar agora</button>' : ''}
      ${e.status === 'paused' ? '<button id="e-resume">Retomar</button>' : ''}` : ''}</div></div>
  ${e.status === 'paused' ? '<div class="card warn-card">Pausado: nenhuma ação passa pelo gate até alguém retomar.</div>' : ''}
  ${e.open_decisions ? `<div class="card warn-card">${e.open_decisions} decisão(ões) aberta(s) — veja na aba <a href="#/employees/${esc(slug)}/decisions">Decisões</a>.</div>` : ''}
  <div class="tabs">${Object.entries(tabs).map(([k, v]) => `<a href="#/employees/${esc(slug)}/${k}" class="${k === key ? 'on' : ''}">${v}</a>`).join('')}</div>
  <div id="tab"></div>`;
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  const status = (to, msg, ask) => ev => (!ask || confirm(ask)) && act(ev.target, () => api(`/employees/${slug}/status`, { method: 'POST', body: { to } }).then(route), msg);
  on('#e-prob', ev => act(ev.target, () => api(`/employees/${slug}/probation`, { method: 'POST' }).then(route), 'Experiência começou: as tarefas estão na fila'));
  on('#e-pause', status('paused', 'Pausado', 'Pausar agora? Nenhuma ação passa até alguém retomar.'));
  on('#e-resume', status('active', 'Retomado'));
  await ({ overview: empOverview, tasks: empTasks, routines: empRoutines, decisions: empDecisions, authority: empAuthority, probation: empProbation, reports: empReports, settings: empSettings })[key]($('#tab'), e);
}

function empOverview(t, e) {
  const m = e.metrics || {};
  const canAssign = ['probation', 'active', 'paused'].includes(e.status);
  t.innerHTML = `<div class="board">${kpi(fmt(m.done), 'Concluídas (30 dias)')}${kpi(fmt(m.waiting), 'Aguardando decisão')}${kpi(fmt(m.failed), 'Com falha')}
    ${kpi(usd(m.cost_usd), 'Custo (30 dias)')}${kpi(m.approvals ? Math.round(100 * m.approved_unedited / m.approvals) + '%' : '—', 'Aprovado sem edição')}
    ${kpi(m.avg_decision_min == null ? '—' : m.avg_decision_min + ' min', 'Tempo de decisão')}</div>
  ${(e.kpi_status || []).length ? `<div class="card mt"><h2>Metas</h2><table><tr><th>Meta</th><th>Medida</th><th>Agora</th><th>Alvo</th><th></th></tr>
    ${e.kpi_status.map(k => `<tr><td data-noi18n>${esc(k.name)}</td><td class="small mute">${esc(KPI_METRIC[k.metric] || '—')}</td><td><b>${kpiVal(k)}</b></td>
      <td class="small">${k.target == null ? '—' : `${k.higher_is_better ? '≥' : '≤'} ${fmt(k.target)}`}</td><td>${kpiPill(k)}</td></tr>`).join('')}</table>
    <div class="mute small mt">Medidas pela plataforma nos últimos 30 dias. O relatório semanal compara cada meta com o alvo.</div></div>` : ''}
  <div class="grid g2 mt">
    <div class="card"><h2>Cargo</h2><dl class="kv guide-kv">
      <dt>Missão</dt><dd data-noi18n>${esc(e.mission)}</dd>
      <dt>Responsabilidades</dt><dd data-noi18n>${(e.responsibilities || []).map(esc).join('<br>')}</dd>
      <dt>Sistemas</dt><dd data-noi18n>${(e.systems || []).map(esc).join(', ') || '—'}</dd>
      <dt>Canais</dt><dd>${(e.channels || []).map(c => `<span class="chip">${esc(c)}</span>`).join(' ')}</dd>
      <dt>Gestor</dt><dd>${esc(e.manager || '—')}</dd><dt>Dono</dt><dd>${esc(e.owner || '—')}</dd>
      <dt>Substitutos</dt><dd>${(e.backups || []).map(esc).join(', ') || '—'}</dd>
      <dt>Metas</dt><dd data-noi18n>${(e.kpis || []).map(k => esc(k.name || k.metric || JSON.stringify(k))).join('<br>') || '—'}</dd>
      <dt>Limites</dt><dd>${usd(e.task_budget_usd)} e ${e.task_time_limit_min} min por tarefa</dd>
      ${e.working_hours ? `<dt>Horário</dt><dd data-noi18n>${esc(e.working_hours)}</dd>` : ''}</dl></div>
    <div class="card"><h2>Entregar uma tarefa</h2>${canAssign ? `
      <label>Título<input id="as-title" maxlength="300" placeholder="o que precisa ser feito"></label>
      <label class="mt">Detalhes<textarea id="as-body" rows="5" placeholder="contexto, dados, prazo e o que você espera receber"></textarea></label>
      <label class="mt">Prioridade<select id="as-prio"><option value="1">Alta</option><option value="2" selected>Normal</option><option value="3">Baixa</option></select></label>
      <div class="row mt"><button id="as-go">Entregar</button></div>
      <div class="mute small mt">Ele trabalha em segundo plano. Ações fora da alçada viram pedidos de decisão para o gestor.</div>`
      : `<div class="mute">${e.status === 'onboarding' ? 'Comece o período de experiência para ele receber tarefas.' : 'Desligado: não recebe mais tarefas.'}</div>`}</div></div>`;
  const b = $('#as-go');
  if (b) b.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/tasks`, { method: 'POST',
    body: { title: $('#as-title').value.trim(), body: $('#as-body').value.trim(), priority: Number($('#as-prio').value) } })
    .then(r => { location.hash = `#/tasks/${r.id}`; }), 'Tarefa entregue');
}

async function empTasks(t, e) {
  const list = await api(`/employees/${e.slug}/tasks`);
  t.innerHTML = `<div class="card">${list.length ? `<table><tr><th>#</th><th>Tarefa</th><th>Status</th><th>Pedida por</th><th>Custo</th><th>Quando</th></tr>
    ${list.map(x => `<tr><td><a href="#/tasks/${x.id}">#${x.id}</a></td><td><a href="#/tasks/${x.id}" data-noi18n>${esc(x.title)}</a>${x.probation ? ' <span class="pill">experiência</span>' : SOURCE_LABEL[x.source] ? ` <span class="chip">${esc(SOURCE_LABEL[x.source])}</span>` : ''}</td>
      <td>${taskPill(x.status)}</td><td class="small">${esc(x.requester)}</td><td class="small">${usd(x.cost_usd)}</td><td class="mute small">${ago(x.created_at)}</td></tr>`).join('')}</table>`
    : '<div class="mute">Nenhuma tarefa ainda.</div>'}</div>`;
}

function empRoutines(t, e) {
  const rs = e.routines || [], w = e.webhook || {};
  t.innerHTML = `<div class="card"><h2>Rotinas</h2>
    <div class="mute small">Trabalho recorrente: a cada disparo vira uma tarefa, no fuso da empresa. Dispara só com ele <b>ativo</b>, e nunca duas
      ao mesmo tempo: se a tarefa anterior da rotina ainda está aberta, o disparo é pulado.</div>
    ${rs.length ? `<table class="mt"><tr><th>Rotina</th><th>Quando</th><th>Próxima</th><th>Última tarefa</th><th>Puladas</th><th></th></tr>
      ${rs.map(r => `<tr data-id="${r.id}"><td><b data-noi18n>${esc(r.title)}</b>${r.body ? `<div class="mute small one-line" data-noi18n style="max-width:280px">${esc(r.body)}</div>` : ''}</td>
        <td class="small"><code class="inline">${esc(r.cron)}</code><div class="mute">${esc(r.when)}</div></td>
        <td class="small">${r.enabled ? esc(r.next_run_local || '—') : '<span class="pill">pausada</span>'}</td>
        <td class="small">${r.last_task_id ? `<a href="#/tasks/${r.last_task_id}">#${r.last_task_id}</a> <span class="mute">${ago(r.last_run_at)}</span>` : '—'}</td>
        <td class="small">${r.skipped}</td>
        <td>${e.can_manage ? `<div class="row" style="gap:4px"><button class="ghost rt-run">Rodar agora</button>
          <button class="ghost rt-toggle">${r.enabled ? 'Pausar' : 'Retomar'}</button><button class="ghost danger rt-del">×</button></div>` : ''}</td></tr>`).join('')}</table>`
      : '<div class="mute mt">Nenhuma rotina ainda.</div>'}
    ${e.can_manage ? `<h3 class="mt">Nova rotina</h3><div class="grid g2">
      <label>Título (vira o título de cada tarefa)<input id="rt-title" placeholder="ex.: Revisar as renovações dos próximos 30 dias"></label>
      <label>Quando<select id="rt-preset">${CRON_PRESETS.map(([c, l]) => `<option value="${c}">${l}</option>`).join('')}<option value="">Outro (cron)…</option></select></label>
      <label>Detalhes<textarea id="rt-body" rows="3" placeholder="o que fazer em cada execução e o que entregar"></textarea></label>
      <label>Cron<input id="rt-cron" data-noi18n value="${CRON_PRESETS[0][0]}" placeholder="min hora dia mês dia-da-semana"></label></div>
      <div class="row mt"><button id="rt-add">Criar rotina</button></div>` : ''}</div>
  <div class="card mt"><h2>Webhook de entrada</h2>
    <div class="mute small">Outros sistemas (CRM, formulários, alertas) criam tarefas para ele com um POST. Mande um <code class="inline">dedupe_key</code>
      por evento: o mesmo evento em ${7} dias não vira uma segunda tarefa.</div>
    <dl class="kv mt"><dt>Status</dt><dd>${w.enabled ? `<span class="pill ok">ligado</span> token terminado em <code class="inline">…${esc(w.hint)}</code>` : '<span class="pill">desligado</span>'}</dd>
      <dt>URL</dt><dd>${copyable(w.url || '')}</dd></dl>
    <div id="wh-out"></div>
    ${e.can_manage ? `<div class="row mt"><button id="wh-gen">${w.enabled ? 'Trocar o token' : 'Gerar token e ligar'}</button>
      ${w.enabled ? '<button class="ghost danger" id="wh-off">Desligar o webhook</button>' : ''}</div>` : ''}</div>`;
  if (!e.can_manage) return;
  const base = `/employees/${e.slug}/routines`;
  const pre = $('#rt-preset'), cron = $('#rt-cron');
  pre.onchange = () => { if (pre.value) cron.value = pre.value; else cron.focus(); };
  $('#rt-add').onclick = ev => act(ev.target, () => api(base, { method: 'POST', body: { title: $('#rt-title').value.trim(),
    body: $('#rt-body').value.trim(), cron: cron.value.trim() } }).then(route), 'Rotina criada');
  t.querySelectorAll('tr[data-id]').forEach(tr => {
    const id = tr.dataset.id, r = rs.find(x => String(x.id) === id);
    const on = (sel, fn) => { const b = $(sel, tr); if (b) b.onclick = fn; };
    on('.rt-run', ev => act(ev.target, () => api(`${base}/${id}/run`, { method: 'POST' }).then(x => { location.hash = `#/tasks/${x.id}`; }), 'Tarefa criada'));
    on('.rt-toggle', ev => act(ev.target, () => api(`${base}/${id}`, { method: 'PATCH', body: { enabled: !r.enabled } }).then(route)));
    on('.rt-del', ev => confirm(`Remover a rotina "${r.title}"? As tarefas que ela já criou ficam.`) &&
      act(ev.target, () => api(`${base}/${id}`, { method: 'DELETE' }).then(route), 'Rotina removida'));
  });
  $('#wh-gen').onclick = ev => (!w.enabled || confirm('Trocar o token? O token atual para de funcionar na hora.')) &&
    act(ev.target, async () => {
      const r = await api(`/employees/${e.slug}/webhook`, { method: 'POST', body: { enabled: true } });
      $('#wh-out').innerHTML = `<div class="card warn-card mt"><b>Copie agora: o token não aparece de novo.</b>
        <div class="mt">${copyable(r.token)}</div><div class="mute small mt">Exemplo:</div><pre class="code small" data-noi18n style="white-space:pre-wrap">${esc(r.example)}</pre></div>`;
    }, 'Token gerado');
  const off = $('#wh-off');
  if (off) off.onclick = ev => confirm('Desligar o webhook? Os sistemas que usam o token param de criar tarefas.') &&
    act(ev.target, () => api(`/employees/${e.slug}/webhook`, { method: 'POST', body: { enabled: false } }).then(route), 'Webhook desligado');
}

async function empDecisions(t, e) {
  const all = (await api('/decisions')).filter(d => d.employee === e.slug);
  t.innerHTML = all.length ? all.map(decisionCard).join('') : '<div class="card mute">Nada esperando por você neste Digital employee.</div>';
  bindDecisions(t, () => route());
}

function suggestionCard(s, can) {
  const body = s.kind === 'authority'
    ? `<div class="mt">${modePill(s.from)} → ${modePill(s.to)} em <b>${esc(ACTION_LABEL[s.action_type] || s.action_type)}</b></div>`
    : `<ul class="small mt">${(s.examples || []).map(x => `<li><a href="#/decisions">#${x.request}</a> ${esc({ approve_edited: 'editada', reject: 'recusada', instruct: 'instruída' }[x.decision] || x.decision)}${x.reason || x.edit ? ` — <span data-noi18n>${esc(x.reason || x.edit)}</span>` : ''}</li>`).join('')}</ul>
      ${can ? `<label class="mt">Lição (vai no prompt de cada tarefa nova)<textarea class="sg-text" rows="2" data-noi18n>${esc(s.lesson)}</textarea></label>` : `<div class="small mt" data-noi18n>${esc(s.lesson)}</div>`}`;
  return `<div class="card mt sg" data-id="${esc(s.id)}"><div class="row between"><b data-noi18n>${esc(s.text)}</b><span class="pill info">${s.evidence} decisões</span></div>${body}
    ${can ? `<div class="row mt"><button class="sg-apply">${s.kind === 'authority' ? 'Aplicar' : 'Virar lição'}</button><button class="ghost sg-dismiss">Dispensar</button></div>` : ''}</div>`;
}

async function empAuthority(t, e) {
  const sugs = await api(`/employees/${e.slug}/suggestions`).catch(() => []);
  const rules = (e.rules || []).map(r => ({ ...r }));
  const row = (r, i) => `<tr data-i="${i}"><td><select class="r-type">${Object.entries(ACTION_LABEL).map(([k, v]) => `<option value="${k}" ${k === r.action_type ? 'selected' : ''}>${v}</option>`).join('')}</select></td>
    <td><select class="r-mode">${Object.entries(MODE_LABEL).map(([k, [v]]) => `<option value="${k}" ${k === r.mode ? 'selected' : ''}>${v}</option>`).join('')}</select></td>
    <td><input class="r-cond" data-noi18n value="${esc(JSON.stringify(r.conditions || []))}" placeholder='[{"field":"amount","op":">","value":1000}]'></td>
    <td><input class="r-appr" value="${esc(r.approver || 'manager')}" style="width:150px"></td>
    <td><input class="r-exp" type="number" value="${r.expires_in_min || 240}" style="width:90px"></td>
    <td><button class="ghost r-del">×</button></td></tr>`;
  const draw = () => {
    t.innerHTML = `${sugs.length ? `<div class="card ok-card"><h2>O que as decisões ensinaram (${sugs.length})</h2>
      <div class="mute small">Sugestões a partir das decisões dos últimos 30 dias. Nada muda sozinho: o gestor aplica ou dispensa.</div>
      ${sugs.map(s => suggestionCard(s, e.can_manage)).join('')}</div>` : ''}
    <div class="grid g2 ${sugs.length ? 'mt' : ''}"><div class="card"><h2>Alçada efetiva</h2><div class="mute small">O que vale agora para cada tipo de ação — regras do cargo, padrão do nível e o piso da empresa (o mais restritivo ganha). Quem aplica é a plataforma, não o prompt.</div>
      <table class="mt"><tr><th>Tipo de ação</th><th>Modo</th><th>De onde vem</th></tr>${(e.authority || []).map(a => `<tr><td>${esc(ACTION_LABEL[a.action_type] || a.action_type)}</td>
        <td>${modePill(a.mode)}${a.separation ? ' <span class="pill">separação de funções</span>' : ''}</td><td class="mute small">${esc(a.source)}</td></tr>`).join('')}</table></div>
      <div class="card"><h2>Como ler</h2><ul class="small">
        <li><b>Sozinho</b>: faz sem perguntar. <b>Faz e avisa</b>: faz e manda um aviso.</li>
        <li><b>Pede aprovação</b>: a tarefa pausa até o gestor aprovar a ação exata (ou editar, recusar ou instruir).</li>
        <li><b>Duas aprovações</b>: duas pessoas diferentes. Com separação de funções, quem pediu a tarefa não aprova.</li>
        <li>Sem resposta no prazo: vai para o substituto; depois expira e ele <b>não faz</b> a ação.</li></ul></div></div>
    <div class="card mt"><h2>Regras do cargo</h2>
      ${e.can_manage ? `<table><tr><th>Tipo de ação</th><th>Modo</th><th>Condições (JSON)</th><th>Quem aprova</th><th>Prazo (min)</th><th></th></tr>${rules.map(row).join('')}</table>
      <div class="row mt"><button class="ghost" id="r-add">+ regra</button><button id="r-save">Salvar alçada</button></div>
      <div class="mute small mt">Quem aprova: manager, team_maintainer ou user:&lt;e-mail&gt;. Condições: field + op (&gt;, &gt;=, &lt;, &lt;=, ==, !=, contains, not_contains, domain_not) + value.</div><div id="r-warn"></div>`
      : (rules.length ? `<table>${rules.map(r => `<tr><td>${esc(ACTION_LABEL[r.action_type])}</td><td>${modePill(r.mode)}</td><td data-noi18n class="small">${esc(JSON.stringify(r.conditions))}</td></tr>`).join('')}</table>` : '<div class="mute">Sem regras próprias: vale o padrão do nível.</div>')}</div>`;
    t.querySelectorAll('.sg').forEach(c => {
      const id = c.dataset.id, txt = $('.sg-text', c);
      const ap = $('.sg-apply', c), dm = $('.sg-dismiss', c);
      if (ap) ap.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/suggestions/${encodeURIComponent(id)}/apply`,
        { method: 'POST', body: { text: txt ? txt.value.trim() : '' } }).then(route), 'Aplicado');
      if (dm) dm.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/suggestions/${encodeURIComponent(id)}/dismiss`,
        { method: 'POST' }).then(route), 'Dispensada');
    });
    if (!e.can_manage) return;
    const read = () => [...t.querySelectorAll('tr[data-i]')].map(tr => ({ action_type: $('.r-type', tr).value, mode: $('.r-mode', tr).value,
      conditions: JSON.parse($('.r-cond', tr).value || '[]'), approver: $('.r-appr', tr).value.trim(), expires_in_min: Number($('.r-exp', tr).value) || 240 }));
    t.querySelectorAll('.r-del').forEach(b => b.onclick = () => {
      try { rules.splice(0, rules.length, ...read()); } catch (err) { /* condição em edição */ }
      rules.splice(Number(b.closest('tr').dataset.i), 1); draw();
    });
    $('#r-add').onclick = () => { try { rules.splice(0, rules.length, ...read()); } catch (err) { /* condição em edição */ } rules.push({ action_type: 'send_external', mode: 'approve' }); draw(); };
    $('#r-save').onclick = ev => act(ev.target, async () => {
      let body; try { body = read(); } catch (err) { throw new Error('Condições: JSON inválido'); }
      const r = await api(`/employees/${e.slug}/authority`, { method: 'PUT', body: { rules: body } });
      e.authority = r.authority; e.rules = r.rules; rules.splice(0, rules.length, ...r.rules.map(x => ({ ...x }))); draw();
      if (r.warnings.length) $('#r-warn').innerHTML = `<div class="card warn-card mt">${r.warnings.map(esc).join('<br>')}</div>`;
    }, 'Alçada salva');
  };
  draw();
}

function empProbation(t, e) {
  const list = e.probation || [];
  const done = list.filter(x => ['done', 'failed', 'cancelled', 'expired'].includes(x.status)).length;
  t.innerHTML = `<div class="card"><h2>Período de experiência (${done}/${list.length})</h2>
    <div class="mute small">Ele faz estas tarefas em stage. Quando todas terminarem, o gestor recebe o pedido de admissão em <a href="#/decisions">Decisões</a> e, aprovando, ele vai para produção.</div>
    ${e.status === 'onboarding' && e.can_manage ? '<div class="mt"><button id="pb-go">Começar experiência</button></div>' : ''}
    ${list.map(x => `<div class="card mt"><div class="row between"><a href="#/tasks/${x.id}"><b data-noi18n>${esc(x.title)}</b></a>${taskPill(x.status)}</div>
      <div class="grid g2 small mt"><div><div class="mute">Resultado esperado</div><div data-noi18n>${esc(x.expected || '—')}</div></div>
      <div><div class="mute">O que ele entregou</div><div class="md small" data-noi18n>${x.result ? mdLite(x.result) : esc(x.error || '—')}</div></div></div></div>`).join('')}</div>`;
  const b = $('#pb-go');
  if (b) b.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/probation`, { method: 'POST' }).then(route), 'Experiência começou');
}

async function empReports(t, e) {
  const list = await api(`/employees/${e.slug}/reports`);
  t.innerHTML = `<div class="card"><div class="row between"><h2>Relatórios</h2>${e.can_manage ? '<div class="row"><button class="ghost" id="rp-now">Gerar diário agora</button><button class="ghost" id="rp-week">Gerar semanal agora</button></div>' : ''}</div>
    <div class="mute small">Um por dia, na hora configurada (fuso da empresa), e um por semana com as metas comparadas ao alvo. Com webhook configurado (Slack ou Teams, o que for da empresa), o resumo também é enviado para lá.</div>
    ${list.length ? list.map(r => `<div class="li"><div class="row between"><span class="pill ${r.period === 'weekly' ? 'info' : ''}">${esc({ daily: 'diário', weekly: 'semanal' }[r.period] || r.period)}</span><span class="mute small">${ago(r.at)} ${r.delivered ? '· enviado' : ''}</span></div>
      <div class="small" data-noi18n style="white-space:pre-wrap">${esc(r.summary)}</div></div>`).join('') : '<div class="mute mt">Nenhum relatório ainda.</div>'}</div>`;
  const b = $('#rp-now');
  if (b) b.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/reports`, { method: 'POST' }).then(route), 'Relatório gerado');
  const bw = $('#rp-week');
  if (bw) bw.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/reports?period=weekly`, { method: 'POST' }).then(route), 'Relatório gerado');
}

function empSettings(t, e) {
  t.innerHTML = `<div class="card"><h2>Cargo e limites</h2><div class="grid g2">
    <label>Cargo<input id="s-title" value="${esc(e.title)}"></label><label>Gestor (e-mail)<input id="s-manager" placeholder="${esc(e.manager || '')}"></label>
    <label style="grid-column:1/-1">Missão<input id="s-mission" value="${esc(e.mission)}"></label>
    <label>Responsabilidades (uma por linha)<textarea id="s-resp" rows="4">${esc((e.responsibilities || []).join('\n'))}</textarea></label>
    <label>Sistemas (uma por linha)<textarea id="s-systems" rows="4">${esc((e.systems || []).join('\n'))}</textarea></label>
    <label>Nível de autonomia (só o gestor muda)<select id="s-level">${Object.entries(LEVEL_LABEL).map(([k, v]) => `<option value="${k}" ${k === e.autonomy_level ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
    <label>Horário de trabalho<input id="s-hours" value="${esc(e.working_hours || '')}"></label>
    <label>Orçamento por tarefa (US$)<input id="s-budget" type="number" step="0.1" value="${e.task_budget_usd}"></label>
    <label>Tempo limite por tarefa (min)<input id="s-limit" type="number" value="${e.task_time_limit_min}"></label>
    <label>Webhook dos relatórios ${e.report_webhook ? '(configurado; deixe vazio para manter)' : ''}<input id="s-hook" placeholder="https://hooks…"></label>
    <label>Hora do relatório diário<input id="s-hour" type="number" min="0" max="23" value="${e.report_hour ?? 18}"></label>
    <label>Relatório semanal<select id="s-week">${EMP_WEEKDAYS.map((d, i) => `<option value="${i}" ${i === (e.report_weekday ?? 0) ? 'selected' : ''}>${d}</option>`).join('')}
      <option value="-1" ${e.report_weekday === -1 ? 'selected' : ''}>Sem relatório semanal</option></select></label></div>
    <h3 class="mt">Metas</h3><div class="mute small">Com uma medida, a plataforma acompanha a meta sozinha e compara com o alvo.</div>
    <div id="s-kpis"></div><button class="ghost small" id="s-kpi-add">+ meta</button>
    <div class="row mt"><button id="s-save">Salvar</button></div></div>
  <div class="card mt"><h2>Lições (${(e.lessons || []).length})</h2>
    <div class="mute small">Vão no prompt de cada tarefa nova. Vêm das sugestões aprovadas na aba Alçada, ou escreva uma aqui.</div>
    ${(e.lessons || []).map(l => `<div class="row between li" data-id="${esc(l.id)}"><span><span data-noi18n>${esc(l.text)}</span>
      <div class="mute small">${esc(l.source === 'manual' ? 'escrita' : 'aprendida')} por ${esc(l.added_by)} · ${ago(l.at)}</div></span>
      <button class="ghost ls-del">Remover</button></div>`).join('') || '<div class="mute mt">Nenhuma lição ainda.</div>'}
    <div class="row mt"><input id="ls-text" placeholder="ex.: sempre copie vendas@empresa.com em e-mails para clientes" style="flex:1"><button class="ghost" id="ls-add">Adicionar</button></div></div>
  <div class="card mt bad-card"><h2>Desligar</h2><div class="mute small">Cancela as tarefas e as decisões abertas e para os containers. O histórico, os relatórios e a auditoria ficam.</div>
    <div class="row mt"><button class="danger" id="s-off" ${e.status === 'offboarded' ? 'disabled' : ''}>${window.t('Desligar')} ${esc(e.name)}</button></div></div>`;
  const kbox = $('#s-kpis');
  const addKpi = k => kbox.insertAdjacentHTML('beforeend', `<div class="grid g3 mt s-kpi">
    <input class="k-name" placeholder="Meta" value="${esc(k.name || '')}" data-noi18n>
    <select class="k-metric"><option value="">— sem medida —</option>${Object.entries(KPI_METRIC).map(([m, l]) => `<option value="${m}" ${m === k.metric ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <input class="k-target" type="number" step="any" placeholder="Alvo" value="${k.target ?? ''}"></div>`);
  (e.kpis || []).forEach(k => addKpi(typeof k === 'string' ? { name: k } : k));
  $('#s-kpi-add').onclick = () => addKpi({});
  const readKpis = () => [...document.querySelectorAll('.s-kpi')].map(r => ({ name: $('.k-name', r).value.trim(), metric: $('.k-metric', r).value,
    target: $('.k-target', r).value === '' ? null : Number($('.k-target', r).value) })).filter(k => k.name || k.metric);
  $('#ls-add').onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/lessons`, { method: 'POST', body: { text: $('#ls-text').value.trim() } }).then(route), 'Lição adicionada');
  t.querySelectorAll('.ls-del').forEach(b => b.onclick = ev => act(ev.target, () => api(`/employees/${e.slug}/lessons/${b.closest('[data-id]').dataset.id}`,
    { method: 'DELETE' }).then(route), 'Lição removida'));
  $('#s-save').onclick = ev => {
    const body = { title: $('#s-title').value.trim(), mission: $('#s-mission').value.trim(), responsibilities: lines($('#s-resp').value),
      systems: lines($('#s-systems').value), working_hours: $('#s-hours').value.trim(), task_budget_usd: Number($('#s-budget').value),
      task_time_limit_min: Number($('#s-limit').value), report_hour: Number($('#s-hour').value),
      report_weekday: Number($('#s-week').value), kpis: readKpis() };
    if ($('#s-manager').value.trim()) body.manager = $('#s-manager').value.trim();
    if ($('#s-hook').value.trim()) body.report_webhook = $('#s-hook').value.trim();
    if ($('#s-level').value !== e.autonomy_level) body.autonomy_level = $('#s-level').value;
    act(ev.target, () => api('/employees/' + e.slug, { method: 'PATCH', body }).then(route), 'Salvo');
  };
  $('#s-off').onclick = ev => {
    const reason = prompt(`Desligar ${e.name}? Motivo (fica na auditoria):`);
    if (reason !== null) act(ev.target, () => api(`/employees/${e.slug}/status`, { method: 'POST', body: { to: 'offboarded', reason } }).then(route), 'Desligado');
  };
}

/* ---------- tarefa: linha do tempo ---------- */
const EVENT_LABEL = { created: 'Criada', run: 'Rodada', tool: 'Ferramenta', gate: 'Alçada', human_request: 'Pedido de decisão',
  decision: 'Decisão', checkpoint: 'Checkpoint', done: 'Concluída', error: 'Erro', note: 'Nota' };
async function taskPage(id) {
  const x = await api('/tasks/' + id);
  const open = (x.requests || []).filter(r => r.status === 'open');
  main.innerHTML = `<a href="javascript:history.back()" class="mute small">← voltar</a>
  <div class="row between"><div><h1 data-noi18n>#${x.id} ${esc(x.title)}</h1><div class="sub">${taskPill(x.status)} pedida por ${esc(x.requester)} · ${when(x.created_at)}
    · ${x.runs} rodada(s) · ${usd(x.cost_usd)}</div></div>
    ${['done', 'failed', 'cancelled', 'expired'].includes(x.status) ? '' : '<button class="ghost danger" id="t-cancel">Cancelar tarefa</button>'}</div>
  ${x.body ? `<div class="card"><h2>Pedido</h2><div data-noi18n style="white-space:pre-wrap">${esc(x.body)}</div>${x.expected ? `<div class="mute small mt">Esperado: <span data-noi18n>${esc(x.expected)}</span></div>` : ''}</div>` : ''}
  ${x.result || x.error ? `<div class="card mt ${x.error ? 'bad-card' : ''}"><h2>${x.error ? 'Erro' : 'Resultado'}</h2><div class="md" data-noi18n>${x.result ? mdLite(x.result) : esc(x.error)}</div></div>` : ''}
  ${open.length ? `<div class="mt">${open.map(decisionCard).join('')}</div>` : ''}
  <div class="card mt"><h2>Linha do tempo</h2>${(x.events || []).map(ev => `<div class="li small"><div class="row between"><b>${esc(EVENT_LABEL[ev.kind] || ev.kind)}</b><span class="mute">${ago(ev.at)}</span></div>
    <div class="mute one-line" data-noi18n title="${esc(JSON.stringify(ev.payload))}">${esc(JSON.stringify(ev.payload))}</div></div>`).join('') || '<div class="mute">—</div>'}</div>`;
  const c = $('#t-cancel');
  if (c) c.onclick = ev => confirm('Cancelar esta tarefa? As decisões abertas dela também são canceladas.') &&
    act(ev.target, () => api(`/tasks/${id}/cancel`, { method: 'POST' }).then(route), 'Tarefa cancelada');
  bindDecisions(main, () => route());
}

/* ---------- decisões (humano no circuito) ---------- */
function decisionCard(d) {
  const head = `<div class="row between"><div><span class="pill ${d.kind === 'approval' ? 'warn' : d.kind === 'admission' ? 'info' : ''}">${esc(KIND_LABEL[d.kind] || d.kind)}</span>
      <a href="#/employees/${esc(d.employee)}"><b>${esc(d.employee_name)}</b></a> <span class="mute small" data-noi18n>${esc(d.employee_title)}</span>
      ${d.task ? `<div class="small">Tarefa <a href="#/tasks/${d.task.id}" data-noi18n>#${d.task.id} ${esc(d.task.title)}</a> · pedida por ${esc(d.task.requester)}</div>` : ''}</div>
    <div class="small mute" style="text-align:right">${when(d.created_at)}${d.expires_at ? `<br>expira em ${esc(new Date(d.expires_at).toLocaleString(window.LOCALE || 'pt-BR'))}` : ''}
      ${d.escalated ? '<br><span class="pill warn">escalado ao substituto</span>' : ''}${d.mine ? '' : `<br>atribuída a ${esc(d.assigned_to || '—')}`}</div></div>`;
  const sel = d.kind === 'approval' || d.kind === 'notice' ? `<input type="checkbox" class="dc-pick" data-id="${d.id}" data-kind="${d.kind}" title="Selecionar"> ` : '';
  let body = '', btns = '';
  if (d.kind === 'approval') {
    body = `<div class="mt"><b>${esc(ACTION_LABEL[d.action_type] || d.action_type)}</b> com <code class="inline">${esc(d.tool)}</code> ${modePill(d.mode)}
      ${d.reversible ? '<span class="pill ok">reversível</span>' : '<span class="pill bad">irreversível</span>'}
      ${d.mode === 'approve_2' ? `<span class="pill">${(d.approvals || []).length}/2 aprovações</span>` : ''}</div>
      ${d.rationale ? `<div class="small mt">Por quê: <span data-noi18n>${esc(d.rationale)}</span></div>` : ''}${payloadView(d.payload)}
      <textarea class="dc-edit code" rows="5" hidden data-noi18n>${esc(JSON.stringify(d.payload, null, 2))}</textarea>
      <input class="dc-reason mt" placeholder="Motivo ou instrução (para recusar ou instruir)">`;
    btns = `<button class="dc-go" data-d="approve">Aprovar</button><button class="ghost dc-edit-open">Editar e aprovar</button>
      <button class="ghost dc-go" data-d="instruct">Instruir</button><button class="ghost danger dc-go" data-d="reject">Recusar</button>`;
  } else if (d.kind === 'question') {
    body = `<div class="mt" data-noi18n><b>${esc(d.question)}</b></div><textarea class="dc-reason mt" rows="3" placeholder="Sua resposta"></textarea>`;
    btns = '<button class="dc-go" data-d="answer">Responder</button>';
  } else if (d.kind === 'admission') {
    body = `<div class="mt">Terminou o período de experiência. <a href="#/employees/${esc(d.employee)}/probation">Ver os resultados</a> e decidir se ele vai para produção.</div>
      <input class="dc-reason mt" placeholder="Comentário (opcional)">`;
    btns = '<button class="dc-go" data-d="approve">Admitir em produção</button><button class="ghost danger dc-go" data-d="reject">Ainda não</button>';
  } else {
    body = `<div class="mt small">Feito: <b>${esc(ACTION_LABEL[d.action_type] || d.action_type)}</b> com <code class="inline">${esc(d.tool)}</code></div>${payloadView(d.payload)}`;
    btns = '<button class="ghost dc-go" data-d="ack">Ciente</button>';
  }
  return `<div class="card mt dc" data-id="${d.id}">${sel}${head}${body}<div class="row mt">${btns}</div></div>`;
}

function bindDecisions(root, after) {
  root.querySelectorAll('.dc').forEach(card => {
    const id = card.dataset.id;
    const edit = $('.dc-edit', card), reason = $('.dc-reason', card);
    const openEdit = $('.dc-edit-open', card);
    if (openEdit) openEdit.onclick = () => {
      if (edit.hidden) { edit.hidden = false; openEdit.textContent = 'Aprovar a versão editada'; return; }
      let payload; try { payload = JSON.parse(edit.value); } catch (err) { return toast('JSON inválido', true); }
      act(openEdit, () => api(`/decisions/${id}`, { method: 'POST', body: { decision: 'approve_edited', edit: payload, reason: reason ? reason.value : '' } }).then(after), 'Aprovado com edição');
    };
    card.querySelectorAll('.dc-go').forEach(b => b.onclick = () => {
      const d = b.dataset.d, why = reason ? reason.value.trim() : '';
      if (['reject', 'instruct', 'answer'].includes(d) && !why && d !== 'reject') return toast(d === 'answer' ? 'Escreva a resposta' : 'Escreva a instrução', true);
      act(b, () => api(`/decisions/${id}`, { method: 'POST', body: { decision: d, reason: why } }).then(r => {
        if (r.status === 'open') toast('Primeira aprovação registrada — falta a segunda, de outra pessoa');
        if (r.message) toast(r.message);
        return after();
      }), { approve: 'Aprovado', reject: 'Recusado', instruct: 'Instrução enviada', answer: 'Resposta enviada', ack: 'Ok' }[d]);
    });
  });
}

async function decisionsPage() {
  const list = await api('/decisions');
  ME.decisions = list.filter(d => d.kind !== 'notice').length; renderSide();
  const mine = list.filter(d => d.mine), other = list.filter(d => !d.mine);
  main.innerHTML = `<div class="row between"><div><h1>Decisões (${list.length})</h1>
    <div class="sub">O que os Digital employees precisam de você: aprovar a ação exata, responder uma pergunta, admitir depois da experiência ou tomar ciência.</div></div>
    ${list.some(d => d.kind === 'approval' || d.kind === 'notice') ? `<div class="row"><button class="ghost" id="dc-all">Selecionar todos</button>
      <button class="ghost" id="dc-ack">Ciente nos avisos selecionados</button><button id="dc-ok">Aprovar selecionados</button></div>` : ''}</div>
  ${list.length ? '' : '<div class="card mute">Nada esperando por você. Quando um Digital employee precisar de uma decisão, ela aparece aqui (e no webhook do relatório, se houver).</div>'}
  ${mine.length ? `<h2 class="mt">Para você (${mine.length})</h2>${mine.map(decisionCard).join('')}` : ''}
  ${other.length ? `<h2 class="mt">Você também pode decidir (${other.length})</h2>${other.map(decisionCard).join('')}` : ''}`;
  bindDecisions(main, decisionsPage);
  const picked = kind => [...document.querySelectorAll('.dc-pick:checked')].filter(c => c.dataset.kind === kind).map(c => Number(c.dataset.id));
  const batch = (btn, kind, decision, msg) => {
    const ids = picked(kind);
    if (!ids.length) return toast(kind === 'notice' ? 'Selecione avisos' : 'Selecione aprovações', true);
    if (decision === 'approve' && !confirm(`Aprovar ${ids.length} ação(ões) exatamente como estão?`)) return;
    act(btn, () => api('/decisions/batch', { method: 'POST', body: { ids, decision } }).then(r => {
      const bad = r.filter(x => x.error); if (bad.length) toast(bad.map(x => `#${x.id}: ${x.error}`).join(' · '), true);
      return decisionsPage();
    }), msg);
  };
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  on('#dc-all', () => document.querySelectorAll('.dc-pick').forEach(c => { c.checked = true; }));
  on('#dc-ok', ev => batch(ev.target, 'approval', 'approve', 'Aprovados'));
  on('#dc-ack', ev => batch(ev.target, 'notice', 'ack', 'Ok'));
}

/* ---------- console do admin: força de trabalho digital ---------- */
async function workforcePage(tab = 'overview') {
  const tabs = { overview: 'Visão geral', catalog: 'Catálogo de ações', floor: 'Piso da empresa' };
  const key = tabs[tab] ? tab : 'overview';
  main.innerHTML = `<h1>Digital employees</h1><div class="sub">A força de trabalho digital da empresa: quem está trabalhando, o que espera decisão, como cada ferramenta é classificada e a alçada mínima que vale para todos.</div>
  <div class="tabs">${Object.entries(tabs).map(([k, v]) => `<a href="#/workforce/${k}" class="${k === key ? 'on' : ''}">${v}</a>`).join('')}</div><div id="tab"></div>`;
  await ({ overview: wfOverview, catalog: wfCatalog, floor: wfFloor })[key]($('#tab'));
}

async function wfOverview(t) {
  const w = await api('/admin/workforce');
  const s = w.statuses || {}, ag = w.decisions_aging || {};
  t.innerHTML = `<div class="board">${kpi(fmt(s.active), 'Ativos')}${kpi(fmt(s.probation), 'Em experiência')}${kpi(fmt(s.paused), 'Pausados')}
    ${kpi(fmt((ag['<1h'] || 0) + (ag['1-4h'] || 0) + (ag['>4h'] || 0)), 'Decisões abertas')}${kpi(fmt(ag['>4h']), 'Abertas há mais de 4h')}${kpi(fmt(w.expired_30d), 'Expiradas (30 dias)')}</div>
  ${w.unclassified_tools ? `<div class="card warn-card mt">${w.unclassified_tools} ferramenta(s) classificada(s) por palpite — revise no <a href="#/workforce/catalog">Catálogo de ações</a>.</div>` : ''}
  <div class="grid g2 mt"><div class="card"><h2>Decisões abertas por idade</h2>${hlist(ag)}</div>
    <div class="card"><h2>Aprovações por tipo (30 dias)</h2>${hlist(Object.fromEntries(Object.entries(w.approvals_by_type_30d || {}).map(([k, v]) => [ACTION_LABEL[k] || k, v])))}</div></div>
  <div class="card mt"><div class="row between"><h2>Todos (${w.employees.length})</h2>
    ${ME.is_admin ? '<button class="danger" id="wf-stop">Parar todos agora</button>' : ''}</div>
    ${w.employees.length ? `<table><tr><th>Digital employee</th><th>Status</th><th>Gestor</th><th>Nível</th><th>Decisões</th><th>Custo 30d</th></tr>
      ${w.employees.map(e => `<tr><td><a href="#/employees/${esc(e.slug)}"><b>${esc(e.name)}</b></a><div class="mute small" data-noi18n>${esc(e.title)}</div></td><td>${empPill(e.status)}</td>
        <td class="small">${esc(e.manager || '—')}</td><td class="small">${esc(LEVEL_LABEL[e.autonomy_level] || e.autonomy_level)}</td>
        <td>${e.open_decisions ? `<span class="pill warn">${e.open_decisions}</span>` : '0'}</td><td class="small">${usd(e.cost_30d)}</td></tr>`).join('')}</table>`
      : '<div class="mute">Nenhum Digital employee ainda. Os donos contratam pelo portal ou pelo MCP.</div>'}</div>`;
  const b = $('#wf-stop');
  if (b) b.onclick = ev => {
    const reason = prompt('Pausar TODOS os Digital employees agora? Nenhuma ação passa pelo gate até cada gestor retomar. Motivo:');
    if (reason !== null) act(ev.target, () => api('/admin/workforce/stop-all', { method: 'POST', body: { reason } }).then(r => { toast(`${r.paused} pausado(s)`); return wfOverview(t); }));
  };
}

async function wfCatalog(t) {
  const list = await api('/admin/action-catalog');
  const review = list.filter(x => x.review).length;
  t.innerHTML = `<div class="card"><h2>Catálogo de ações (${list.length})</h2>
    <div class="mute small">Cada ferramenta que um Digital employee usa tem um tipo de ação, e é o tipo que decide a alçada. A plataforma classifica sozinha na primeira vez;
      as marcadas <span class="pill warn">revisar</span> foram por palpite (pelo nome) — confirme ou corrija. ${review ? `<b>${review} para revisar.</b>` : ''}</div>
    ${list.length ? `<table class="mt"><tr><th>Ferramenta</th><th>Tipo de ação</th><th>Risco</th><th>Reversível</th><th>Classificada por</th><th></th></tr>
      ${list.map((c, i) => `<tr data-ref="${esc(c.tool_ref)}"><td><code class="inline" data-noi18n>${esc(c.tool_ref)}</code> ${c.review ? '<span class="pill warn">revisar</span>' : ''}</td>
        <td><select class="c-type">${Object.entries(ACTION_LABEL).map(([k, v]) => `<option value="${k}" ${k === c.action_type ? 'selected' : ''}>${v}</option>`).join('')}</select></td>
        <td><input class="c-risk" type="number" min="1" max="5" value="${c.risk}" style="width:70px"></td>
        <td><input type="checkbox" class="c-rev" ${c.reversible ? 'checked' : ''}></td><td class="mute small">${esc(c.classified_by)}</td>
        <td><button class="ghost c-save">${c.review ? 'Confirmar' : 'Salvar'}</button></td></tr>`).join('')}</table>`
      : '<div class="mute mt">Vazio: as ferramentas entram aqui na primeira vez que um Digital employee tenta usá-las.</div>'}</div>`;
  t.querySelectorAll('.c-save').forEach(b => b.onclick = () => {
    const tr = b.closest('tr');
    act(b, () => api('/admin/action-catalog', { method: 'PUT', body: { tool_ref: tr.dataset.ref, action_type: $('.c-type', tr).value,
      risk: Number($('.c-risk', tr).value), reversible: $('.c-rev', tr).checked } }).then(() => wfCatalog(t)), 'Classificação salva');
  });
}

async function wfFloor(t) {
  const list = await api('/admin/authority-floor');
  t.innerHTML = `<div class="card"><h2>Piso da empresa</h2>
    <div class="mute small">A alçada mínima que vale para todos os Digital employees, acima das regras de cada cargo: uma regra mais frouxa que o piso não vale.
      Separação de funções: quem pediu a tarefa não pode aprovar a ação.</div>
    <table class="mt"><tr><th>Tipo de ação</th><th>Modo mínimo</th><th>Separação de funções</th></tr>
    ${list.map(f => `<tr data-t="${f.action_type}"><td>${esc(ACTION_LABEL[f.action_type] || f.action_type)}</td>
      <td><select class="f-mode">${Object.entries(MODE_LABEL).map(([k, [v]]) => `<option value="${k}" ${k === f.min_mode ? 'selected' : ''}>${v}</option>`).join('')}</select></td>
      <td><input type="checkbox" class="f-sep" ${f.separation ? 'checked' : ''}></td></tr>`).join('')}</table>
    ${ME.is_admin ? '<div class="row mt"><button id="f-save">Salvar piso</button></div>' : ''}</div>`;
  const b = $('#f-save');
  if (b) b.onclick = () => act(b, () => api('/admin/authority-floor', { method: 'PUT', body: { items: [...t.querySelectorAll('tr[data-t]')]
    .map(tr => ({ action_type: tr.dataset.t, min_mode: $('.f-mode', tr).value, separation: $('.f-sep', tr).checked })) } }).then(() => wfFloor(t)), 'Piso salvo');
}
