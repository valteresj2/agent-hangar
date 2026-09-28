/* Login, empresa, times, usuários, aprovações, acesso a agentes e SSO/SCIM. Usa os helpers de app.js
   ($, api, esc, toast, act, ME…), que só são chamados depois que os dois scripts carregaram. */

const ROLE_LABEL = { admin: 'Admin', auditor: 'Auditor', member: 'Membro', maintainer: 'Mantenedor', developer: 'Developer', consumer: 'Consumer' };
const ROLE_HELP = {
  maintainer: 'gerencia membros, aprova produção e pedidos de acesso',
  developer: 'cria, edita e testa os agentes do time',
  consumer: 'usa os agentes do time (conectar, playground, uso)',
};
const PROVIDER_ICON = { google: 'G', microsoft: '⊞', github: '◐', oauth2: '⚿' };

/* ---------- boot e login ---------- */
async function boot() {
  if (location.hash.startsWith('#/login')) return showLogin();
  try { ME = await api('/me'); }
  catch (e) { if (!(e instanceof AuthError)) main.innerHTML = `<div class="card"><h2>Erro</h2>${esc(e.message)}</div>`; return; }
  document.body.classList.remove('login-mode');
  $('#login').hidden = true;
  renderSide();
  route();
}

function renderSide() {
  const ok = need => !need || (need === 'admin' && ME.is_admin) || (need === 'auditor' && ME.is_auditor) || (need === 'builder' && (ME.can_create_agents || ME.is_admin));
  document.querySelectorAll('nav a').forEach(a => { a.hidden = !ok(a.dataset.need); });
  const badge = $('#appr-badge'); if (badge) { badge.textContent = ME.pending || ''; badge.hidden = !ME.pending; }
  const u = ME.user;
  const role = ME.is_admin ? 'Admin' : ME.is_auditor ? 'Auditor' : (ME.teams[0] ? `${ROLE_LABEL[ME.teams[0].role]} · ${ME.teams[0].name}` : 'Membro');
  $('#whoami').innerHTML = `<div class="who">${u && u.avatar_url ? `<img src="${esc(u.avatar_url)}" alt="" referrerpolicy="no-referrer">` : `<span class="av">${esc((u ? (u.name || u.email) : 'A')[0].toUpperCase())}</span>`}
    <div><div class="small"><b>${esc(u ? (u.name || u.email) : 'Sessão de emergência')}</b></div><div class="mute small">${esc(role)}</div></div></div>`;
}

async function showLogin() {
  ME = null;
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const err = params.get('error');
  const next = location.hash.startsWith('#/login') ? '#/' : (location.hash || '#/');
  const { providers } = await fetch('/api/auth/providers').then(r => r.json()).catch(() => ({ providers: [] }));
  document.body.classList.add('login-mode');
  const box = $('#login');
  box.hidden = false;
  box.innerHTML = `<div class="login-card">
    <div class="brand"><span class="logo">⌂</span> Agent Hangar</div>
    <h1>Entrar</h1><div class="sub">Use a conta da empresa.</div>
    ${err ? `<div class="card bad-card small">${esc(err)}</div>` : ''}
    <div class="sso-list">${providers.map(p => `<a class="sso-btn" href="/api/auth/login/${encodeURIComponent(p.id)}?next=${encodeURIComponent(next)}"><span class="ic">${PROVIDER_ICON[p.id] || '⚿'}</span>Entrar com ${esc(p.label)}</a>`).join('')
      || '<div class="mute small">Nenhum login corporativo configurado ainda. Entre com o token de admin e configure em <b>SSO e SCIM</b>.</div>'}</div>
    <details class="mt" ${providers.length ? '' : 'open'}><summary>Entrar com token (emergência, chave admin ou token pessoal)</summary>
      <div class="row mt"><input id="lg-token" type="password" placeholder="ADMIN_TOKEN ou ah_…" style="flex:1" autocomplete="off"><button id="lg-go">Entrar</button></div>
      <div class="mute small mt">O token vira uma sessão (cookie seguro) — não fica salvo no navegador.</div></details></div>`;
  const go = async () => {
    const r = await fetch('/api/auth/token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: $('#lg-token').value.trim() }) });
    if (!r.ok) { const d = await r.json().catch(() => ({})); toast(d.detail || 'Token inválido', true); return; }
    location.hash = next; location.reload();
  };
  $('#lg-go').onclick = go; $('#lg-token').onkeydown = e => e.key === 'Enter' && go();
}

/* ---------- agente: visão de quem não é do time ---------- */
async function overviewLimited(t, a) {
  const mineReq = a.access === 'viewer' ? ((await api('/approvals').catch(() => ({ my_access: [] }))).my_access || []).find(r => r.agent === a.slug && r.status === 'pending') : null;
  const useCard = a.access === 'viewer'
    ? `<div class="card hero"><h2>Quer usar este agente?</h2><div>Ele é do time <b>${esc(a.team ? a.team.name : '—')}</b>. ${mineReq ? `Seu pedido de ${ago(mineReq.created_at)} atrás está <b>aguardando</b> o mantenedor do time.` : 'Peça acesso: um mantenedor do time aprova, e aí você conecta o agente nas suas ferramentas (aba Conectar).'}</div>
       ${mineReq ? '' : '<button class="mt" id="ov-req">Solicitar acesso</button>'}</div>`
    : `<div class="card hero"><h2>Pronto para usar</h2><div>Conecte nas suas ferramentas pela aba <a href="#/agents/${a.slug}/connect">Conectar</a> (Claude, Codex, OpenCode, LibreChat, Open WebUI…) ou teste no <a href="#/agents/${a.slug}/playground">Playground</a>.</div></div>`;
  t.innerHTML = `${useCard}<div class="grid g2 mt">
    <div class="card"><h2>Registro</h2><dl class="kv">
      <dt>Slug</dt><dd>${copyable(a.slug)}</dd><dt>Saída final</dt><dd>${esc(a.final_output)}</dd>
      <dt>Time</dt><dd>${esc(a.team ? a.team.name : '—')}</dd><dt>Contato</dt><dd>${esc(a.owner) || '—'}</dd>
      <dt>Visibilidade</dt><dd>${visPill(a.visibility)}</dd><dt>Versão</dt><dd>v${a.version}</dd>
      <dt>Produção</dt><dd>${a.prod ? '<span class="pill ok">no ar</span>' : '<span class="mute">fora do ar</span>'}</dd>
      <dt>Último teste</dt><dd>${a.last_test ? `${pill(a.last_test.status)} <span class="mute small">${esc(a.last_test.summary)}</span>` : '—'}</dd></dl></div>
    <div class="card"><h2>Como funciona</h2><div class="mute small">Instruções, spec, versões e logs são visíveis só para o time dono${a.expose_spec ? '' : ' (o time pode liberar a spec em Acesso → “expor spec”)'}.</div>
      ${can(a, 'consume') ? `<h3>Endpoints</h3>${Object.entries(a.endpoints || {}).map(([k, v]) => `<div class="small"><b>${k}</b> ${copyable(v)}</div>`).join('')}` : ''}</div></div>`;
  const b = $('#ov-req'); if (b) b.onclick = () => requestAccessDialog(a.slug);
}

/* ---------- agente: aba Acesso (mantenedor/admin) ---------- */
async function agentAccess(t, a) {
  const [grants, teamList] = await Promise.all([api(`/agents/${a.slug}/grants`), api('/teams')]);
  const targets = teamList.filter(x => ME.is_admin || x.my_role === 'maintainer');
  t.innerHTML = `<div class="grid g2">
    <div class="card"><h2>Quem pode ver e usar</h2>
      <label>Visibilidade<select id="ac-vis">${Object.entries({ private: 'só o time vê e usa', org: 'aparece no catálogo da empresa; uso sob pedido aprovado', open: 'qualquer pessoa da empresa usa direto' })
        .map(([k, v]) => `<option value="${k}" ${a.visibility === k ? 'selected' : ''}>${VIS[k]} — ${v}</option>`).join('')}</select></label>
      <label class="row small mt"><input type="checkbox" id="ac-spec" style="width:auto" ${a.expose_spec ? 'checked' : ''}> Expor instruções e spec (somente leitura) para quem não é do time</label>
      <label class="mt">Time dono<select id="ac-team">${targets.map(x => `<option value="${esc(x.slug)}" ${a.team && a.team.slug === x.slug ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label>
      <div class="mute small mt">Ao restringir o acesso, as chaves de quem perdeu permissão são revogadas na hora.</div>
      <button id="ac-save" class="mt">Salvar</button></div>
    <div class="card"><h2>Pedidos e acessos concedidos (${grants.length})</h2>
      ${grants.length ? `<table><tr><th>Pessoa</th><th>Motivo</th><th>Status</th><th></th></tr>${grants.map(g => `<tr><td><b>${esc(g.user_name || g.user)}</b><div class="mute small">${esc(g.user)}</div></td>
        <td class="small">${esc(g.reason) || '<span class="mute">—</span>'}</td><td>${g.status === 'pending' ? '<span class="pill warn">pendente</span>' : '<span class="pill ok">liberado</span>'}<div class="mute small">${ago(g.created_at)} atrás</div></td>
        <td>${g.status === 'pending' ? `<button class="gr-ok" data-id="${g.id}">Aprovar</button> <button class="ghost gr-no" data-id="${g.id}">Recusar</button>` : `<button class="ghost gr-rev" data-id="${g.id}">Revogar</button>`}</td></tr>`).join('')}</table>`
        : '<div class="mute">Nenhum pedido. Com visibilidade “empresa”, pessoas de outros times pedem acesso pelo catálogo.</div>'}</div></div>`;
  $('#ac-save').onclick = e => act(e.target, () => api(`/agents/${a.slug}/access`, { method: 'PATCH', body: { visibility: $('#ac-vis').value, expose_spec: $('#ac-spec').checked, team: $('#ac-team').value } }).then(route), 'Acesso atualizado');
  const decide = (sel, verb, msg) => t.querySelectorAll(sel).forEach(b => b.onclick = e => act(e.target, () => api(`/access-requests/${b.dataset.id}/${verb}`, { method: 'POST' }).then(route), msg));
  decide('.gr-ok', 'approve', 'Acesso liberado'); decide('.gr-no', 'reject', 'Pedido recusado');
  t.querySelectorAll('.gr-rev').forEach(b => b.onclick = e => confirm('Revogar o acesso? As chaves dessa pessoa para este agente param na hora.') &&
    act(e.target, () => api(`/access-requests/${b.dataset.id}/revoke`, { method: 'POST' }).then(route), 'Acesso revogado'));
}

/* ---------- aprovações ---------- */
const REQ_STATUS = { pending: ['pendente', 'warn'], approved: ['aprovado', 'ok'], rejected: ['recusado', 'bad'], revoked: ['revogado', ''], superseded: ['sem efeito (nova versão)', ''] };
const reqPill = s => { const [t, c] = REQ_STATUS[s] || [s, '']; return `<span class="pill ${c}">${esc(t)}</span>`; };

async function approvalsPage() {
  const r = await api('/approvals');
  ME.pending = r.to_decide.length; renderSide();
  main.innerHTML = `<h1>Aprovações</h1><div class="sub">Promoções para produção (quatro olhos: quem pediu não aprova) e pedidos de uso de agentes dos seus times</div>
  <div class="card"><h2>Para você decidir (${r.to_decide.length})</h2>
    ${r.to_decide.length ? r.to_decide.map(x => x.kind === 'promotion' ? `
      <div class="card mt"><div class="row between"><div><span class="pill info">produção</span> <a href="#/agents/${x.agent}"><b>${esc(x.agent_name)}</b></a> v${x.version}
        <div class="mute small">pedido por ${esc(x.requested_by)} · ${ago(x.created_at)} atrás${x.note ? ` · “${esc(x.note)}”` : ''}</div>
        ${x.stale ? '<div class="bad-text small">O agente mudou depois do pedido — aprovar não vale; peça de novo.</div>' : ''}</div>
        <div class="row"><button class="pr-ok" data-id="${x.id}" ${x.stale ? 'disabled' : ''}>Aprovar e publicar</button><button class="ghost pr-no" data-id="${x.id}">Recusar</button></div></div></div>` : `
      <div class="card mt"><div class="row between"><div><span class="pill">acesso</span> <b>${esc(x.user_name || x.user)}</b> <span class="mute small">${esc(x.user)}</span> quer usar <a href="#/agents/${x.agent}"><b>${esc(x.agent_name)}</b></a>
        <div class="mute small">${ago(x.created_at)} atrás${x.reason ? ` · “${esc(x.reason)}”` : ''}</div></div>
        <div class="row"><button class="ac-ok" data-id="${x.id}">Liberar</button><button class="ghost ac-no" data-id="${x.id}">Recusar</button></div></div></div>`).join('')
      : '<div class="mute">Nada pendente.</div>'}</div>
  <div class="grid g2 mt">
    <div class="card"><h2>Seus pedidos de acesso</h2>${r.my_access.length ? `<table><tr><th>Agente</th><th>Status</th><th></th></tr>${r.my_access.map(x => `<tr><td><a href="#/agents/${x.agent}">${esc(x.agent_name)}</a><div class="mute small">${ago(x.created_at)} atrás</div></td><td>${reqPill(x.status)}</td>
      <td>${x.status === 'approved' ? `<button class="ghost my-rev" data-id="${x.id}">Abrir mão</button>` : ''}</td></tr>`).join('')}</table>` : '<div class="mute">Nenhum. Procure agentes no <a href="#/agents/catalog">catálogo da empresa</a>.</div>'}</div>
    <div class="card"><h2>Suas promoções</h2>${r.my_promotions.length ? `<table><tr><th>Agente</th><th>Versão</th><th>Status</th></tr>${r.my_promotions.map(x => `<tr><td><a href="#/agents/${x.agent}">${esc(x.agent_name)}</a><div class="mute small">${ago(x.created_at)} atrás</div></td><td>v${x.version}</td><td>${reqPill(x.status)}${x.decided_by ? `<div class="mute small">por ${esc(x.decided_by)}</div>` : ''}</td></tr>`).join('')}</table>` : '<div class="mute">Nenhuma.</div>'}</div></div>`;
  const bind = (sel, url, msg, ask) => document.querySelectorAll(sel).forEach(b => b.onclick = e => (!ask || confirm(ask)) &&
    act(e.target, () => api(url(b.dataset.id), { method: 'POST', body: {} }).then(approvalsPage), msg));
  bind('.pr-ok', id => `/promotions/${id}/approve`, 'Aprovado — agente publicado em produção', 'Aprovar e publicar esta versão em produção?');
  bind('.pr-no', id => `/promotions/${id}/reject`, 'Promoção recusada');
  bind('.ac-ok', id => `/access-requests/${id}/approve`, 'Acesso liberado');
  bind('.ac-no', id => `/access-requests/${id}/reject`, 'Pedido recusado');
  bind('.my-rev', id => `/access-requests/${id}/revoke`, 'Acesso devolvido', 'Abrir mão do acesso? Suas chaves para este agente param de funcionar.');
}

/* ---------- times ---------- */
const budgetBar = t => {
  if (!t.budget_usd_month) return `<div class="mute small">Gasto no mês: ${usd(t.spent_month)} · sem orçamento</div>`;
  const pct = Math.min(100, Math.round(100 * t.spent_month / t.budget_usd_month));
  return `<div class="small row between"><span>Orçamento do mês</span><b>${usd(t.spent_month)} / ${usd(t.budget_usd_month)}</b></div>
    <div class="hbar budget ${t.budget_state}"><i style="width:${pct}%"></i></div>${t.budget_state === 'over' ? `<div class="bad-text small">Estourado${t.budget_enforce ? ' — chamadas bloqueadas' : ''}</div>` : ''}`;
};

async function teamsPage() {
  const list = await api('/teams');
  main.innerHTML = `<div class="row between"><div><h1>Times</h1><div class="sub">Cada agente pertence a um time. Papéis: <b>mantenedor</b> (${ROLE_HELP.maintainer}), <b>developer</b> (${ROLE_HELP.developer}), <b>consumer</b> (${ROLE_HELP.consumer}).</div></div></div>
  ${ME.is_admin ? `<details class="card"><summary>+ Novo time</summary><div class="grid g4 mt"><input id="tm-name" placeholder="nome (ex.: Dados e BI)"><input id="tm-desc" placeholder="descrição (opcional)">
    <label class="row small"><input type="checkbox" id="tm-appr" checked style="width:auto"> produção exige aprovação</label><button id="tm-go">Criar time</button></div></details>` : ''}
  <div class="grid g3 mt">${list.map(t => `<div class="card click-card" onclick="location.hash='#/teams/${t.slug}'"><div class="row between"><h2>${esc(t.name)}</h2>${t.my_role ? `<span class="pill ok">${esc(ROLE_LABEL[t.my_role])}</span>` : ''}</div>
    <div class="mute small">${esc(t.description) || '&nbsp;'}</div><div class="row mt small"><span>👥 ${t.members} membros</span><span>🤖 ${t.agents} agentes</span>${t.require_approval ? '<span class="chip">aprovação p/ produção</span>' : ''}</div>
    <div class="mt">${budgetBar(t)}</div></div>`).join('')}</div>`;
  const go = $('#tm-go');
  if (go) go.onclick = e => act(e.target, () => api('/teams', { method: 'POST', body: { name: $('#tm-name').value.trim(), description: $('#tm-desc').value, require_approval: $('#tm-appr').checked } }).then(t => location.hash = '#/teams/' + t.slug), 'Time criado');
}

async function teamDetail(slug) {
  const t = await api('/teams/' + slug);
  const [members, agents] = await Promise.all([api(`/teams/${slug}/members`).catch(() => null), api('/agents')]);
  const mine = agents.filter(a => a.team && a.team.slug === slug);
  const maint = ME.is_admin || t.my_role === 'maintainer';
  const roleSel = (v, id) => `<select class="mb-role" data-id="${id}" style="width:auto" ${maint ? '' : 'disabled'}>${['maintainer', 'developer', 'consumer'].map(r => `<option value="${r}" ${r === v ? 'selected' : ''}>${ROLE_LABEL[r]}</option>`).join('')}</select>`;
  main.innerHTML = `<a href="#/teams" class="mute small">← Times</a><div class="row between"><div><h1>${esc(t.name)} ${t.my_role ? `<span class="pill ok">${esc(ROLE_LABEL[t.my_role])}</span>` : ''}</h1><div class="sub">${esc(t.description) || ''}</div></div>
    ${ME.is_admin && t.id !== 1 ? '<button id="tm-del" class="danger">Excluir time</button>' : ''}</div>
  <div class="grid g2">
    <div class="card"><h2>Membros (${members ? members.length : t.members})</h2>
      ${maint ? `<div class="row"><input id="mb-email" placeholder="e-mail da pessoa" style="flex:1"><select id="mb-role" style="width:auto">${['consumer', 'developer', 'maintainer'].map(r => `<option value="${r}">${ROLE_LABEL[r]}</option>`).join('')}</select><button id="mb-add">Adicionar</button></div>
        <div class="mute small">Quem ainda não entrou fica pré-cadastrado e cai no time no primeiro login.</div>` : ''}
      ${members ? `<table class="mt"><tr><th>Pessoa</th><th>Papel</th><th>Origem</th><th></th></tr>${members.map(m => `<tr class="${m.active ? '' : 'mute'}"><td><b>${esc(m.name || m.email)}</b><div class="mute small">${esc(m.email)}${m.active ? '' : ' · desativado'}</div></td>
        <td>${roleSel(m.role, m.user_id)}</td><td><span class="chip">${esc(m.source)}</span></td><td>${maint ? `<button class="ghost mb-rm" data-id="${m.user_id}" data-n="${esc(m.email)}">Remover</button>` : ''}</td></tr>`).join('')}</table>`
        : '<div class="mute">A lista de membros é visível para quem é do time.</div>'}</div>
    <div class="card"><h2>Configuração</h2>
      <label>Nome<input id="ts-name" value="${esc(t.name)}" ${maint ? '' : 'disabled'}></label>
      <label class="mt">Descrição<input id="ts-desc" value="${esc(t.description)}" ${maint ? '' : 'disabled'}></label>
      <label class="row small mt"><input type="checkbox" id="ts-appr" style="width:auto" ${t.require_approval ? 'checked' : ''} ${ME.is_admin ? '' : 'disabled'}> Produção exige aprovação de outro mantenedor (quatro olhos)</label>
      <div class="grid g2 mt"><label>Orçamento mensal (US$)<input id="ts-budget" type="number" min="0" step="1" value="${t.budget_usd_month ?? ''}" placeholder="sem limite" ${ME.is_admin ? '' : 'disabled'}></label>
        <label class="row small" style="align-self:end"><input type="checkbox" id="ts-enf" style="width:auto" ${t.budget_enforce ? 'checked' : ''} ${ME.is_admin ? '' : 'disabled'}> bloquear chamadas ao estourar</label></div>
      <div class="mt">${budgetBar(t)}</div>
      ${maint ? '<button id="ts-save" class="mt">Salvar</button>' : ''}${ME.is_admin ? '' : '<div class="mute small mt">Aprovação e orçamento são definidos por admins.</div>'}</div></div>
  <div class="card mt"><h2>Agentes do time (${mine.length})</h2>${mine.length ? `<table><tr><th>Agente</th><th>Status</th><th>Visibilidade</th><th>Custo 7d</th></tr>${mine.map(a => `<tr class="click" onclick="location.hash='#/agents/${a.slug}'"><td><b>${esc(a.name)}</b></td><td>${pill(a.status)}</td><td>${visPill(a.visibility)}</td><td>${usd(a.cost_7d)}</td></tr>`).join('')}</table>` : '<div class="mute">Nenhum agente.</div>'}</div>`;
  const reload = () => teamDetail(slug);
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  on('#mb-add', e => act(e.target, () => api(`/teams/${slug}/members`, { method: 'POST', body: { email: $('#mb-email').value.trim(), role: $('#mb-role').value } }).then(reload), 'Membro adicionado'));
  document.querySelectorAll('.mb-role').forEach(s => s.onchange = () => api(`/teams/${slug}/members/${s.dataset.id}`, { method: 'PATCH', body: { role: s.value } }).then(() => toast('Papel atualizado')).catch(e => { toast(e.message, true); reload(); }));
  document.querySelectorAll('.mb-rm').forEach(b => b.onclick = e => confirm(`Remover ${b.dataset.n} do time? As chaves dessa pessoa para agentes do time param na hora.`) &&
    act(e.target, () => api(`/teams/${slug}/members/${b.dataset.id}`, { method: 'DELETE' }).then(reload), 'Membro removido'));
  on('#ts-save', e => {
    const body = { name: $('#ts-name').value.trim(), description: $('#ts-desc').value };
    if (ME.is_admin) Object.assign(body, { require_approval: $('#ts-appr').checked, budget_usd_month: num($('#ts-budget').value) ?? 0, budget_enforce: $('#ts-enf').checked });
    return act(e.target, () => api('/teams/' + slug, { method: 'PATCH', body }).then(reload), 'Time atualizado');
  });
  on('#tm-del', e => confirm(`Excluir o time ${t.name}?`) && act(e.target, () => api('/teams/' + slug, { method: 'DELETE' }).then(() => location.hash = '#/teams'), 'Time excluído'));
}

/* ---------- usuários ---------- */
async function usersPage() {
  const list = await api('/users');
  const render = q => {
    const rows = list.filter(u => (u.email + u.name).toLowerCase().includes(q.toLowerCase()));
    $('#u-rows').innerHTML = rows.map(u => `<tr class="${u.active ? '' : 'mute'}"><td><b>${esc(u.name || u.email)}</b><div class="mute small">${esc(u.email)}</div></td>
      <td>${u.provider ? `<span class="chip">${esc(u.provider)}</span>` : '<span class="mute small">pré-cadastro</span>'}${u.scim ? ' <span class="chip">scim</span>' : ''}</td>
      <td>${ME.is_admin ? `<select class="u-role" data-id="${u.id}" style="width:auto">${['member', 'auditor', 'admin'].map(r => `<option value="${r}" ${r === u.org_role ? 'selected' : ''}>${ROLE_LABEL[r]}</option>`).join('')}</select>` : esc(ROLE_LABEL[u.org_role])}</td>
      <td>${u.teams.map(t => `<span class="chip" title="${esc(ROLE_LABEL[t.role])}">${esc(t.name)} · ${esc(ROLE_LABEL[t.role])}</span>`).join('') || '<span class="mute small">—</span>'}</td>
      <td class="mute small">${u.last_login_at ? ago(u.last_login_at) + ' atrás' : 'nunca'}</td>
      <td>${ME.is_admin ? `<button class="ghost u-act ${u.active ? '' : 'on'}" data-id="${u.id}" data-a="${u.active ? 0 : 1}" data-n="${esc(u.email)}">${u.active ? 'Desativar' : 'Reativar'}</button>` : (u.active ? '' : '<span class="pill bad">desativado</span>')}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Nenhum usuário</td></tr>';
    document.querySelectorAll('.u-role').forEach(s => s.onchange = () => api(`/users/${s.dataset.id}`, { method: 'PATCH', body: { org_role: s.value } }).then(() => toast('Papel atualizado')).catch(e => toast(e.message, true)));
    document.querySelectorAll('.u-act').forEach(b => b.onclick = e => (b.dataset.a === '1' || confirm(`Desativar ${b.dataset.n}? Sessões encerradas e todas as chaves revogadas na hora.`)) &&
      act(e.target, () => api(`/users/${b.dataset.id}`, { method: 'PATCH', body: { active: b.dataset.a === '1' } }).then(usersPage), 'Usuário atualizado'));
  };
  main.innerHTML = `<div class="row between"><div><h1>Usuários</h1><div class="sub">Criados no primeiro login (OAuth2), por SCIM ou pré-cadastrados. <b>Admin</b>: tudo. <b>Auditor</b>: lê tudo (uso, custo, auditoria, specs). <b>Membro</b>: conforme os times.</div></div>
    <input id="u-q" placeholder="Buscar…" style="max-width:240px"></div>
  ${ME.is_admin ? `<details class="card"><summary>+ Pré-cadastrar usuário</summary><div class="grid g4 mt"><input id="nu-email" placeholder="e-mail"><input id="nu-name" placeholder="nome (opcional)">
    <select id="nu-role"><option value="member">Membro</option><option value="auditor">Auditor</option><option value="admin">Admin</option></select><button id="nu-go">Cadastrar</button></div></details>` : ''}
  <div class="card mt scroll"><table><tr><th>Pessoa</th><th>Origem</th><th>Papel na empresa</th><th>Times</th><th>Último login</th><th></th></tr><tbody id="u-rows"></tbody></table></div>`;
  render(''); $('#u-q').oninput = e => render(e.target.value);
  const go = $('#nu-go');
  if (go) go.onclick = e => act(e.target, () => api('/users', { method: 'POST', body: { email: $('#nu-email').value.trim(), name: $('#nu-name').value, org_role: $('#nu-role').value } }).then(usersPage), 'Usuário cadastrado');
}

/* ---------- SSO (OAuth2) e SCIM ---------- */
const SSO_FIELDS = {
  google: [['allowed_domains', 'Domínios permitidos (vírgula) — ex.: empresa.com.br']],
  microsoft: [['tenant', 'Tenant (ID ou domínio, ex.: empresa.onmicrosoft.com)'], ['allowed_domains', 'Domínios permitidos (opcional)'], ['fetch_groups', 'Ler grupos (GroupMember.Read.All, consentimento de admin)', 'bool']],
  github: [['orgs', 'Organizações do GitHub exigidas (vírgula)'], ['fetch_groups', 'Ler times do GitHub para mapear', 'bool']],
  oauth2: [['label', 'Nome no botão (ex.: Keycloak)'], ['authorize_url', 'Authorization URL'], ['token_url', 'Token URL'], ['userinfo_url', 'Userinfo URL'],
    ['scopes', 'Escopos (espaço)'], ['groups_field', 'Campo de grupos no userinfo (padrão groups)'], ['allowed_domains', 'Domínios permitidos (opcional)'],
    ['trust_email', 'Confiar no e-mail sem email_verified (só se o provedor garante)', 'bool']],
};
const SSO_HELP = {
  google: 'Google Cloud Console → APIs e serviços → Credenciais → ID do cliente OAuth (Aplicativo da Web). Tela de consentimento “Interno” restringe à sua organização.',
  microsoft: 'Entra ID → Registros de aplicativo → Novo registro (conta só deste diretório) → Certificados e segredos. Permissões delegadas: User.Read (e GroupMember.Read.All para grupos).',
  github: 'GitHub → Settings → Developer settings → OAuth Apps (ou da organização). Escopos pedidos: read:user, user:email, read:org.',
  oauth2: 'Qualquer provedor OAuth2 com endpoint de userinfo: Keycloak, Okta, Auth0, Authentik… Para SAML, use o Keycloak como ponte (identity brokering).',
};

async function ssoPage() {
  const [c, keys, teamList] = await Promise.all([api('/sso'), api('/keys'), api('/teams')]);
  const scimKeys = keys.filter(k => k.scopes.includes('scim') && !k.revoked);
  const val = (p, k) => { const v = p.settings[k]; return Array.isArray(v) ? v.join(', ') : (v ?? ''); };
  main.innerHTML = `<h1>SSO e SCIM</h1><div class="sub">Login corporativo por OAuth2 e provisionamento automático de usuários e grupos. Segredos ficam criptografados; variáveis OAUTH_* do .env valem como padrão.</div>
  <div class="grid g2">${c.providers.map(p => `<div class="card"><div class="row between"><h2><span class="sso-ic">${PROVIDER_ICON[p.id]}</span> ${esc(p.id === 'oauth2' ? 'OAuth2 genérico' : p.label)}</h2>
      ${p.ready ? '<span class="pill ok">ativo</span>' : p.enabled && p.client_id ? '<span class="pill warn">incompleto</span>' : '<span class="pill">desligado</span>'}</div>
    <div class="mute small">${esc(SSO_HELP[p.id])}</div>
    <div class="small mt">Redirect URI (cadastre no provedor): ${copyable(p.redirect_uri)}</div>
    <label class="row small mt"><input type="checkbox" id="sp-${p.id}-en" style="width:auto" ${p.enabled ? 'checked' : ''}> Ativar login com este provedor</label>
    <div class="grid g2 mt"><label>Client ID<input id="sp-${p.id}-cid" value="${esc(p.client_id)}"></label>
      <label>Client secret<input id="sp-${p.id}-sec" type="password" placeholder="${p.has_secret ? '•••••• (salvo — vazio mantém)' : 'segredo do app'}" autocomplete="new-password"></label></div>
    ${SSO_FIELDS[p.id].map(([k, label, kind]) => kind === 'bool'
      ? `<label class="row small mt"><input type="checkbox" id="sp-${p.id}-${k}" style="width:auto" ${p.settings[k] ? 'checked' : ''}> ${esc(label)}</label>`
      : `<label class="mt">${esc(label)}<input id="sp-${p.id}-${k}" value="${esc(val(p, k))}"></label>`).join('')}
    <button class="mt sp-save" data-p="${p.id}">Salvar</button></div>`).join('')}</div>

  <div class="card mt"><h2>Grupos → times</h2><div class="mute small">Quem está no grupo entra no time com o papel indicado a cada login (OAuth2) ou mudança no diretório (SCIM). Quem foi adicionado à mão não é mexido.
    Microsoft: ID ou nome do grupo · GitHub: <code>org/time</code> · OAuth2: valor do claim de grupos · SCIM: nome do grupo provisionado.</div>
    <table class="mt"><tr><th>Origem</th><th>Grupo externo</th><th>Time</th><th>Papel</th><th></th></tr>
    ${c.mappings.map(m => `<tr><td><span class="chip">${esc(m.provider)}</span></td><td><code class="inline">${esc(m.external_group)}</code></td><td>${esc(m.team)}</td><td>${esc(ROLE_LABEL[m.role])}</td><td><button class="ghost mp-del" data-id="${m.id}">Remover</button></td></tr>`).join('') || '<tr><td colspan="5" class="mute">Nenhum mapeamento</td></tr>'}</table>
    <div class="grid g4 mt"><select id="mp-prov">${['microsoft', 'github', 'oauth2', 'scim'].map(x => `<option>${x}</option>`).join('')}</select><input id="mp-grp" placeholder="grupo externo">
      <select id="mp-team">${teamList.map(t => `<option value="${esc(t.slug)}">${esc(t.name)}</option>`).join('')}</select>
      <div class="row"><select id="mp-role" style="width:auto">${['consumer', 'developer', 'maintainer'].map(r => `<option value="${r}">${ROLE_LABEL[r]}</option>`).join('')}</select><button id="mp-add">Adicionar</button></div></div></div>

  <div class="grid g2 mt">
    <div class="card"><h2>SCIM 2.0 (provisionamento)</h2><div class="mute small">No Entra ID: Aplicativos empresariais → seu app → Provisionamento → Automático. Okta: app SCIM 2.0. Desligar alguém no diretório encerra as sessões e revoga as chaves dele aqui.</div>
      <div class="small mt">URL do locatário: ${copyable(c.scim_url)}</div>
      <div class="row mt"><input id="sc-name" placeholder="nome do token (ex.: entra-id)" value="entra-id"><button id="sc-go">Gerar token SCIM</button></div><div id="sc-new"></div>
      ${scimKeys.length ? `<table class="mt"><tr><th>Token</th><th>Último uso</th><th></th></tr>${scimKeys.map(k => `<tr><td><b>${esc(k.name)}</b> <code class="inline">${esc(k.prefix)}…</code></td><td class="mute small">${k.last_used_at ? ago(k.last_used_at) + ' atrás' : 'nunca'}</td><td><button class="ghost sc-rev" data-id="${k.id}">Revogar</button></td></tr>`).join('')}</table>` : ''}</div>
    <div class="card"><h2>Primeiro acesso e emergência</h2><div class="small">E-mails em <code>BOOTSTRAP_ADMIN_EMAILS</code> viram admin no login: ${c.bootstrap_admins.length ? c.bootstrap_admins.map(e => `<span class="chip">${esc(e)}</span>`).join('') : '<span class="mute">nenhum definido</span>'}</div>
      <div class="mute small mt">O <code>ADMIN_TOKEN</code> continua funcionando como acesso de emergência (“Entrar com token”): guarde-o num cofre e use só se o SSO cair.</div></div></div>`;
  document.querySelectorAll('.sp-save').forEach(b => b.onclick = e => {
    const p = b.dataset.p; const settings = {};
    SSO_FIELDS[p].forEach(([k, , kind]) => { const el = $(`#sp-${p}-${k}`); settings[k] = kind === 'bool' ? el.checked : el.value.trim(); });
    return act(e.target, () => api('/sso/' + p, { method: 'PUT', body: { enabled: $(`#sp-${p}-en`).checked, client_id: $(`#sp-${p}-cid`).value.trim(), client_secret: $(`#sp-${p}-sec`).value, settings } }).then(ssoPage), 'Provedor salvo');
  });
  $('#mp-add').onclick = e => act(e.target, () => api('/sso/mappings', { method: 'POST', body: { provider: $('#mp-prov').value, external_group: $('#mp-grp').value.trim(), team: $('#mp-team').value, role: $('#mp-role').value } }).then(ssoPage), 'Mapeamento criado');
  document.querySelectorAll('.mp-del').forEach(b => b.onclick = e => act(e.target, () => api('/sso/mappings/' + b.dataset.id, { method: 'DELETE' }).then(ssoPage), 'Removido'));
  $('#sc-go').onclick = e => act(e.target, async () => {
    const r = await api('/keys', { method: 'POST', body: { name: $('#sc-name').value.trim() || 'scim', scopes: ['scim'] } });
    $('#sc-new').innerHTML = `<div class="card mt warn-card"><b>Copie agora — não será exibido de novo</b> (cole como “Token secreto” no diretório):${copyable(r.key)}</div>`;
  });
  document.querySelectorAll('.sc-rev').forEach(b => b.onclick = e => confirm('Revogar o token SCIM? O diretório para de sincronizar.') && act(e.target, () => api('/keys/' + b.dataset.id, { method: 'DELETE' }).then(ssoPage), 'Token revogado'));
}
