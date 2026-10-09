/* Plugins: conectar qualquer sistema à plataforma com um manifesto declarativo (ferramentas HTTP, credencial do time,
   tipos de ação para a alçada, configurações e skills). Catálogo, rascunho ou importação de OpenAPI, revisão de quatro
   olhos (admin) e instalação por time. Usa os helpers de app.js e o ACTION_LABEL de employees.js. */

const PLUGIN_STATUS = { draft: ['Rascunho', ''], pending: ['Em revisão', 'warn'], approved: ['Liberado', 'ok'],
  rejected: ['Recusado', 'bad'], disabled: ['Desligado', 'bad'] };
const AUTH_LABEL = { none: 'sem autenticação', api_key: 'chave de API', bearer: 'token (Bearer)', basic: 'usuário e senha (Basic)' };
const plStatus = s => { const [t, c] = PLUGIN_STATUS[s] || [s, '']; return `<span class="pill ${c}">${esc(t)}</span>`; };
const plActions = acts => Object.entries(acts || {}).map(([k, n]) =>
  `<span class="pill ${['send_external', 'financial', 'delete', 'publish', 'prod_change', 'speak_for_company', 'run_code'].includes(k) ? 'warn' : ''}"><span>${esc(ACTION_LABEL[k] || k)}</span> · ${n}</span>`).join(' ');
const PLUGIN_EXAMPLE = `name: meu-erp
title: Meu ERP
version: 1.0.0
description: Consulta faturas e clientes do ERP.
publisher: TI
base_url: https://erp.exemplo.com/api
auth: {type: api_key, in: header, name: X-API-Key, label: Chave da API}
settings:
  - {key: company_id, title: Código da empresa, required: true}
tools:
  - name: get_invoice
    description: Uma fatura pelo número.
    method: GET
    path: /companies/{{settings.company_id}}/invoices/{number}
    parameters: {type: object, properties: {number: {type: string}}, required: [number]}
  - name: send_invoice
    description: Envia a fatura por e-mail ao cliente.
    method: POST
    path: /invoices/{number}/send
    action: send_external
    parameters: {type: object, properties: {number: {type: string}}, required: [number]}
skills:
  - {name: glossario, content: "Fatura vencida: mais de 30 dias sem pagamento."}
test: {tool: get_invoice, args: {number: "1"}}
`;

async function pluginsPage() {
  const list = await api('/plugins');
  main.innerHTML = `<div class="row between"><div><h1>Plugins (${list.length})</h1>
    <div class="sub">Conecte um sistema da empresa (ERP, CRM, faturamento…) com um manifesto: as ferramentas, a credencial do time e o tipo de cada ação para a alçada.
      Nada de código rodando na plataforma, e o segredo nunca chega ao agente.</div></div>
    ${ME.can_create_agents ? '<a href="#/plugins/new"><button>+ Novo plugin</button></a>' : ''}</div>
  ${list.length ? `<div class="grid g3">${list.map(p => `<div class="card agent-card">
      <div class="row between"><a href="#/plugins/${esc(p.name)}"><b data-noi18n>${esc(p.title)}</b></a>${plStatus(p.status)}</div>
      <div class="mute small"><code class="inline" data-noi18n>${esc(p.name)}</code> v${esc(p.approved_version || p.version)}${p.publisher ? ` · <span data-noi18n>${esc(p.publisher)}</span>` : ''}</div>
      <div class="small one-line mt" data-noi18n title="${esc(p.description)}">${esc(p.description)}</div>
      <div class="small mt"><span class="chip" data-noi18n>${esc(p.permissions.host)}</span> <span class="mute">${esc(AUTH_LABEL[p.permissions.auth] || p.permissions.auth)}</span></div>
      <div class="row small mt" style="gap:4px;flex-wrap:wrap">${plActions(p.permissions.actions)}</div>
      <div class="mute small mt">${p.installed_for.length ? `<span>Instalado:</span> ${p.installed_for.map(t => t === 'org' ? window.t('empresa') : esc(t)).join(', ')}` : '<span>Não instalado</span>'}</div></div>`).join('')}</div>`
    : `<div class="card empty"><h2>Nenhum plugin ainda</h2><div class="mute">Escreva o manifesto ou importe o OpenAPI do sistema. Depois de aprovado por um admin, o mantenedor do time instala com a credencial do time e os agentes usam com <code class="inline">plugins: [nome]</code> na spec.</div></div>`}`;
}

async function pluginNewPage() {
  const teams = (ME.teams || []).filter(t => ['developer', 'maintainer'].includes(t.role));
  main.innerHTML = `<a href="#/plugins" class="mute small">← Plugins</a><h1>Novo plugin</h1>
  <div class="grid g2"><div class="card"><h2>Importar de um OpenAPI</h2>
      <div class="mute small">Cole o OpenAPI 3 (JSON ou YAML) do sistema: cada operação vira uma ferramenta, com um palpite do tipo de ação. Revise o resultado ao lado antes de salvar.</div>
      <label class="mt">OpenAPI<textarea id="pn-oa" rows="10" class="code" data-noi18n placeholder='{"openapi": "3.0.0", …}'></textarea></label>
      <div class="grid g2"><label>Nome (opcional)<input id="pn-oa-name" data-noi18n placeholder="meu-erp"></label>
        <label>base_url (se o OpenAPI não tiver)<input id="pn-oa-base" data-noi18n placeholder="https://…"></label></div>
      <div class="row mt"><button class="ghost" id="pn-import">Gerar o manifesto</button></div></div>
    <div class="card"><h2>Manifesto</h2>
      <div class="mute small">YAML ou JSON. <code class="inline">base_url</code> é o único host com que o plugin fala; cada ferramenta declara o <code class="inline">action</code> (o tipo que decide a alçada).</div>
      <textarea id="pn-manifest" rows="22" class="code mt" data-noi18n>${esc(PLUGIN_EXAMPLE)}</textarea>
      <label class="mt">Time dono<select id="pn-team"><option value="">— só eu —</option>${teams.map(t => `<option value="${esc(t.slug)}">${esc(t.name || t.slug)}</option>`).join('')}</select></label>
      <div class="row mt"><button id="pn-save">Salvar rascunho</button></div></div></div>`;
  let source = 'manual';
  $('#pn-import').onclick = ev => act(ev.target, () => api('/plugins/import-openapi', { method: 'POST', body: {
    document: $('#pn-oa').value, name: $('#pn-oa-name').value.trim(), base_url: $('#pn-oa-base').value.trim() } }).then(r => {
    $('#pn-manifest').value = JSON.stringify(r.manifest, null, 2); source = 'openapi';
    toast(`${r.manifest.tools.length} ${window.t('ferramenta(s) geradas: revise as ações')}`);
  }));
  $('#pn-save').onclick = ev => act(ev.target, () => api('/plugins', { method: 'POST', body: {
    manifest: $('#pn-manifest').value, team: $('#pn-team').value || null, source } }).then(p => { location.hash = `#/plugins/${p.name}`; }), 'Rascunho salvo');
}

function plInstallForm(p, m, inst, team) {
  const id = team || 'org';
  const settings = m.settings || [];
  return `<div class="card mt pl-inst" data-team="${esc(team || '')}"><div class="row between"><h3>${team ? `<span>Time</span> <span data-noi18n>${esc(team)}</span>` : 'Empresa toda'}</h3>
      ${inst ? (inst.enabled ? '<span class="pill ok">instalado</span>' : '<span class="pill">pausado</span>') : '<span class="pill">não instalado</span>'}</div>
    <div class="grid g2">${settings.map(s => `<label>${esc(s.title || s.key)}${s.required ? ' *' : ''}${s.description ? `<div class="mute small" data-noi18n>${esc(s.description)}</div>` : ''}
        <input class="pl-set" data-k="${esc(s.key)}" data-secret="${s.secret ? 1 : 0}" ${s.secret ? 'type="password" autocomplete="off"' : ''} data-noi18n
          value="${s.secret ? '' : esc((inst && inst.settings[s.key]) ?? s.default ?? '')}" placeholder="${s.secret && inst && inst.secrets[s.key] ? window.t('cadastrado — digite outro para trocar') : ''}"></label>`).join('')}
      ${m.auth.type !== 'none' ? `<label>${esc(m.auth.label || AUTH_LABEL[m.auth.type])}${m.auth.type === 'basic' ? ' <span class="mute small">(usuário:senha)</span>' : ''}
        <input class="pl-cred" type="password" autocomplete="off" placeholder="${inst && inst.credential ? window.t('cadastrada — digite outra para trocar') : ''}"></label>` : ''}</div>
    ${inst ? `<div class="mute small mt"><span>Chamadas:</span> ${inst.stats.calls || 0} · <span>erros:</span> ${inst.stats.errors || 0}${inst.stats.last_call ? ` · <span>última</span> <span>${ago(inst.stats.last_call)}</span>` : ''}
      ${inst.last_test ? ` · <span>teste:</span> ${inst.last_test.ok ? '<span class="pill ok">ok</span>' : `<span class="pill bad">falhou</span> <span data-noi18n>${esc(inst.last_test.sample || '')}</span>`}` : ''}</div>` : ''}
    <div class="row mt"><button class="pl-save" data-id="${esc(id)}">${inst ? 'Salvar' : 'Instalar'}</button>
      ${inst ? `<button class="ghost pl-test">Testar conexão</button><button class="ghost pl-toggle">${inst.enabled ? 'Pausar' : 'Retomar'}</button>
        <button class="ghost danger pl-del">Desinstalar</button>` : ''}</div></div>`;
}

async function pluginDetail(name) {
  const p = await api('/plugins/' + name);
  const m = p.approved_manifest || p.manifest, perm = p.permissions;
  const draftDiffers = p.approved_manifest && JSON.stringify(p.approved_manifest) !== JSON.stringify(p.manifest);
  const installs = Object.fromEntries((p.installs || []).map(i => [i.team || '', i]));
  const targets = [...(p.install_teams || []).map(t => t.slug), ...(ME.is_admin ? [''] : [])];
  main.innerHTML = `<a href="#/plugins" class="mute small">← Plugins</a>
  <div class="row between"><div><h1 data-noi18n>${esc(p.title)}</h1><div class="sub"><code class="inline" data-noi18n>${esc(p.name)}</code> ${plStatus(p.status)}
    ${p.approved_version ? `<span>em uso:</span> v${esc(p.approved_version)}` : ''}${draftDiffers ? ` · <span>rascunho</span> v${esc(p.version)}` : ''}
    ${p.team ? ` · <span>time</span> <span data-noi18n>${esc(p.team)}</span>` : ''}</div></div>
    ${ME.is_admin && p.approved_version ? `<button class="ghost ${p.status === 'disabled' ? '' : 'danger'}" id="pl-off">${p.status === 'disabled' ? 'Religar' : 'Desligar'}</button>` : ''}</div>
  <div class="mute" data-noi18n>${esc(p.description)}</div>
  ${p.status === 'rejected' && p.review_note ? `<div class="card bad-card mt"><b>Recusado:</b> <span data-noi18n>${esc(p.review_note)}</span></div>` : ''}
  ${p.can_review ? `<div class="card warn-card mt"><h2>Revisão</h2><div class="small">Enviado por ${esc(p.submitted_by)}. Confira o host, a autenticação e o tipo de cada ação: é o tipo que decide se o agente faz sozinho ou pede aprovação.</div>
    <input id="pl-note" class="mt" placeholder="Comentário (obrigatório para recusar)"><div class="row mt"><button id="pl-approve">Aprovar v${esc(p.version)}</button>
    <button class="ghost danger" id="pl-reject">Recusar</button></div></div>` : ''}
  <div class="grid g2 mt"><div class="card"><h2>Permissões</h2><dl class="kv">
      <dt>Fala com</dt><dd><code class="inline" data-noi18n>${esc(perm.host)}</code>${perm.templated_host ? ' <span class="mute small">(definido na instalação)</span>' : ''}</dd>
      <dt>Autenticação</dt><dd>${esc(AUTH_LABEL[perm.auth] || perm.auth)}</dd>
      <dt>Ações</dt><dd>${plActions(perm.actions)}</dd>
      <dt>Segredos</dt><dd>${perm.secrets.length ? perm.secrets.map(s => `<code class="inline" data-noi18n>${esc(s)}</code>`).join(' ') : '—'}${perm.auth !== 'none' ? ` <span class="mute small">+ ${esc(window.t('credencial'))}</span>` : ''}</dd></dl>
      ${perm.risky.length ? `<div class="small mt warn-card card"><span>Ações que mudam algo fora da empresa ou têm risco alto:</span> ${perm.risky.map(a => `<b>${esc(ACTION_LABEL[a] || a)}</b>`).join(', ')}. <span>A alçada de cada agente decide (por padrão, pedem aprovação).</span></div>` : ''}</div>
    <div class="card"><h2>Ferramentas (${m.tools.length})</h2><table class="small">${m.tools.map(t => `<tr><td><code class="inline" data-noi18n>${esc(t.name)}</code>
      <div class="mute" data-noi18n>${esc(t.description || '')}</div></td><td><code class="inline" data-noi18n>${esc(t.method)} ${esc(t.path)}</code></td>
      <td>${esc(ACTION_LABEL[t.action] || t.action)}</td></tr>`).join('')}</table>
      ${(m.skills || []).length ? `<div class="mute small mt"><span>Skills:</span> ${m.skills.map(s => `<code class="inline" data-noi18n>${esc(s.name)}</code>`).join(' ')}</div>` : ''}</div></div>
  ${p.approved_version && p.status !== 'disabled' ? `<h2 class="mt">Instalação</h2>
    <div class="mute small">Cada time instala com a própria credencial (o mantenedor do time; um admin também instala para a empresa toda). Os agentes do time usam com
      <code class="inline">plugins: [${esc(p.name)}]</code> na spec, e as ferramentas chegam como <code class="inline">plugin-${esc(p.name)}__…</code>.</div>
    ${targets.length ? targets.map(t => plInstallForm(p, p.approved_manifest, installs[t], t)).join('') : '<div class="card mute mt">Só o mantenedor de um time (ou um admin) instala.</div>'}` : ''}
  ${p.can_edit ? `<div class="card mt"><div class="row between"><h2>Manifesto ${p.status === 'approved' ? '' : `<span class="mute small">(${esc(PLUGIN_STATUS[p.status] ? window.t(PLUGIN_STATUS[p.status][0]) : p.status)})</span>`}</h2>
      ${['draft', 'rejected'].includes(p.status) ? '<button id="pl-submit">Enviar para revisão</button>' : ''}</div>
    <div class="mute small">Para mudar um plugin aprovado, suba a <code class="inline">version</code>: a versão nova passa pela revisão e as instalações seguem na aprovada até lá.</div>
    <textarea id="pl-yaml" rows="18" class="code mt" data-noi18n>${esc(p.yaml)}</textarea>
    <div class="row mt"><button class="ghost" id="pl-update">Salvar rascunho</button>${!p.approved_version || ME.is_admin ? '<button class="ghost danger" id="pl-delete">Apagar</button>' : ''}</div></div>` : ''}`;
  const on = (sel, fn) => { const b = $(sel); if (b) b.onclick = fn; };
  on('#pl-submit', ev => act(ev.target, () => api(`/plugins/${name}/submit`, { method: 'POST' }).then(route), 'Enviado para revisão'));
  on('#pl-update', ev => act(ev.target, () => api(`/plugins/${name}`, { method: 'PUT', body: { manifest: $('#pl-yaml').value } }).then(route), 'Rascunho salvo'));
  on('#pl-delete', ev => confirm(`${window.t('Apagar o plugin')} ${name}?`) && act(ev.target, () => api(`/plugins/${name}`, { method: 'DELETE' }).then(() => { location.hash = '#/plugins'; })));
  on('#pl-approve', ev => act(ev.target, () => api(`/plugins/${name}/review`, { method: 'POST', body: { decision: 'approve', note: $('#pl-note').value } }).then(route), 'Aprovado'));
  on('#pl-reject', ev => act(ev.target, () => api(`/plugins/${name}/review`, { method: 'POST', body: { decision: 'reject', note: $('#pl-note').value } }).then(route), 'Recusado'));
  on('#pl-off', ev => act(ev.target, () => api(`/plugins/${name}/${p.status === 'disabled' ? 'enable' : 'disable'}`, { method: 'POST' }).then(route)));
  main.querySelectorAll('.pl-inst').forEach(card => {
    const team = card.dataset.team || null;
    $('.pl-save', card).onclick = ev => {
      const body = { team, settings: {}, secrets: {} };
      card.querySelectorAll('.pl-set').forEach(i => { if (i.dataset.secret === '1') { if (i.value) body.secrets[i.dataset.k] = i.value; } else body.settings[i.dataset.k] = i.value; });
      const cred = $('.pl-cred', card);
      if (cred && cred.value) body.credential = cred.value;
      act(ev.target, () => api(`/plugins/${name}/install`, { method: 'PUT', body }).then(route), 'Instalado');
    };
    const tst = $('.pl-test', card);
    if (tst) tst.onclick = ev => act(ev.target, () => api(`/plugins/${name}/install/test`, { method: 'POST', body: { team } })
      .then(r => { toast(r.ok ? window.t('Conexão ok') : `${window.t('Falhou')}: ${r.sample}`, !r.ok); return route(); }));
    const tog = $('.pl-toggle', card);
    if (tog) tog.onclick = ev => act(ev.target, () => api(`/plugins/${name}/install`, { method: 'PUT', body: { team, enabled: !installs[team || ''].enabled } }).then(route));
    const del = $('.pl-del', card);
    if (del) del.onclick = ev => confirm(window.t('Desinstalar? Os agentes do time deixam de usar este plugin.')) &&
      act(ev.target, () => api(`/plugins/${name}/install${team ? `?team=${encodeURIComponent(team)}` : ''}`, { method: 'DELETE' }).then(route), 'Desinstalado');
  });
}
