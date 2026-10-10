/* Página "Início" do portal do usuário (/app): o dia a dia de quem usa e constrói agentes, numa tela só.
   Dados: GET /api/me/home (já filtrado pelas permissões de quem está logado). */
const HOME_ATTN_IC = { bad: 'x', warn: 'approve', info: 'chat' };
const HOME_ACCESS = { maintainer: 'mantenedor', developer: 'developer', consumer: 'consumer', granted: 'pode usar', admin: 'admin' };
const HOME_REQ = { pending: ['pendente', 'warn'], approved: ['aprovado', 'ok'], rejected: ['recusado', 'bad'], revoked: ['revogado', ''], superseded: ['substituído', ''] };
const homeReqPill = s => { const [t, c] = HOME_REQ[s] || [s, '']; return `<span class="pill ${c}">${t}</span>`; };
const homeFirstName = n => String(n || '').split(/[\s@]/)[0];

async function homePage() {
  const [h, dec] = await Promise.all([api('/me/home'), api('/decisions').catch(() => [])]);
  const toDecide = dec.filter(d => d.kind !== 'notice');
  const c = h.counts;
  const builder = ME.can_create_agents || ME.is_admin;
  const hour = new Date().getHours();
  const hello = hour < 12 ? 'Bom dia' : hour < 18 ? 'Boa tarde' : 'Boa noite';
  main.innerHTML = `
  <div class="row between"><div><h1>${ME.user ? `${hello}, ${esc(homeFirstName(ME.user.name || ME.user.email))}` : hello}</h1>
    <div class="sub">O que está acontecendo com os seus agentes${ME.teams.length ? ` e com ${ME.teams.length === 1 ? 'o seu time' : 'os seus times'}` : ''}</div></div>
    <div class="row">${builder ? '<a href="#/agents/new"><button>+ Novo agente</button></a>' : ''}<a href="#/agents/catalog"><button class="ghost">Catálogo da empresa</button></a></div></div>

  <div class="card attn-card ${h.attention.length ? '' : 'ok'}"><h2>${h.attention.length ? `Precisa de atenção (${h.attention.length})` : 'Tudo certo por aqui'}</h2>
    ${h.attention.length ? `<ul class="attn">${h.attention.map(x => `<li class="${x.level}"><span class="attn-ic">${icon(HOME_ATTN_IC[x.level] || 'chat')}</span>
      <a href="${esc(x.link)}">${esc(x.text)}</a></li>`).join('')}</ul>`
      : '<div class="mute">Nenhum teste reprovado, agendamento com falha, erro recente ou orçamento estourando nos seus agentes.</div>'}</div>

  ${toDecide.length ? `<div class="card mt warn-card"><div class="row between"><h2>Para você decidir: Digital employees (${toDecide.length})</h2><a href="#/decisions" class="small">Abrir Decisões →</a></div>
    <ul class="list">${toDecide.slice(0, 5).map(d => `<li><a href="#/decisions"><b>${esc(d.employee_name)}</b> · ${esc({ approval: 'aprovação', question: 'pergunta', admission: 'admissão' }[d.kind] || d.kind)}${d.tool ? ` <code class="inline">${esc(d.tool)}</code>` : ''}</a>
      <span class="mute small">${ago(d.created_at)}</span></li>`).join('')}</ul></div>` : ''}

  <div class="board mt">
    ${kpi(fmt(c.agents), 'Meus agentes')}
    ${kpi(fmt(c.in_production), 'No ar em produção')}
    ${kpi(fmt(c.to_decide), 'Pedidos para você decidir')}
    ${kpi(fmt(c.my_pending), 'Pedidos seus em aberto')}
    ${kpi(fmt(h.my_usage.requests), 'Suas chamadas (30 dias)')}
    ${kpi(usd(h.my_usage.cost_usd), 'Seu custo (30 dias)')}
  </div>

  <div class="card mt"><div class="row between"><h2>Meus agentes</h2><a href="#/agents" class="small">Ver todos com detalhes →</a></div>
    ${h.agents.length ? `<div class="grid g3 mt">${h.agents.slice(0, 9).map(homeAgentCard).join('')}</div>`
      : `<div class="mute">Você ainda não tem agentes. ${builder ? 'Crie um em <a href="#/agents/new">Novo agente</a>, a partir de um <a href="#/templates">template</a>, ou' : ''}
         procure no <a href="#/agents/catalog">catálogo da empresa</a> e peça acesso.</div>`}</div>

  <div class="grid g2 mt">
    <div class="card"><div class="row between"><h2>Pedidos</h2><a href="#/approvals" class="small">Abrir aprovações →</a></div>
      ${h.to_decide.length ? `<h3 class="small up">Aguardando a sua decisão</h3><ul class="list">${h.to_decide.map(r => `<li><a href="#/approvals">${r.kind === 'promotion'
        ? `Publicar <b>${esc(r.agent_name)}</b> v${r.version} em produção` : `Acesso de ${esc(r.user_name || r.user)} a <b>${esc(r.agent_name)}</b>`}</a>
        <span class="mute small">${ago(r.created_at)}</span></li>`).join('')}</ul>` : ''}
      <h3 class="small up">Os seus pedidos</h3>
      ${[...h.my_requests.access.map(r => ({ ...r, what: `Acesso a <b>${esc(r.agent_name)}</b>` })),
         ...h.my_requests.promotions.map(r => ({ ...r, what: `Produção de <b>${esc(r.agent_name)}</b> v${r.version}` }))]
        .sort((x, y) => (y.created_at || '').localeCompare(x.created_at || '')).slice(0, 6)
        .map(r => `<div class="row between li"><span>${r.what} ${homeReqPill(r.status)}</span><span class="mute small">${r.decided_by ? `por ${esc(r.decided_by)}, ` : ''}${ago(r.decided_at || r.created_at)}</span></div>`).join('')
        || '<div class="mute small">Nenhum pedido. Para usar um agente de outro time, peça acesso no catálogo da empresa.</div>'}</div>

    <div class="card"><h2>Orçamento e uso</h2>
      ${h.teams.length ? h.teams.map(t => `<div class="small mt"><div class="row between"><a href="#/teams/${esc(t.slug)}"><b>${esc(t.name)}</b></a>
        <span>${usd(t.spent_month)}${t.budget_usd_month ? ` de ${usd(t.budget_usd_month)} no mês` : ' no mês (sem orçamento definido)'}</span></div>
        ${t.budget_usd_month ? `<div class="meter ${t.budget_state}"><i style="width:${Math.min(100, 100 * t.spent_month / t.budget_usd_month)}%"></i></div>` : ''}</div>`).join('')
        : '<div class="mute small">Você ainda não faz parte de um time.</div>'}
      <h3 class="small up mt">O seu uso nos últimos 30 dias</h3>
      ${h.my_usage.by_agent.length ? h.my_usage.by_agent.map(u => `<div class="row between li small"><a href="#/agents/${esc(u.slug)}">${esc(u.name)}</a>
        <span>${fmt(u.requests)} chamadas · ${usd(u.cost_usd)}</span></div>`).join('') + `<div class="mute small mt">${fmt(h.my_usage.tokens)} tokens no total</div>`
        : '<div class="mute small">Sem uso com as suas chaves ou sessão ainda.</div>'}</div>
  </div>

  <div class="grid g2 mt">
    <div class="card"><h2>Próximos agendamentos</h2>
      ${h.schedules.length ? h.schedules.map(s => `<div class="row between li"><span><a href="#/agents/${esc(s.agent)}/schedules"><b>${esc(s.agent_name)}</b></a>
        <span class="mute small">${esc(s.name || s.when)}</span></span><span class="small">${esc(s.next_run_local || '—')}</span></div>`).join('')
        : '<div class="mute small">Nenhum agendamento nos seus agentes. Um agente pode rodar sozinho no dia e hora que você escolher (aba Agendamentos).</div>'}</div>

    <div class="card"><div class="row between"><h2>Minhas conexões</h2><a href="#/connect" class="small">Conectar ferramenta →</a></div>
      <div class="mute small">Chaves suas em uso (Claude, Codex, LibreChat…). Revogue as que não usa mais.</div>
      ${h.keys.length ? h.keys.map(k => `<div class="row between li"><span><b>${esc(k.name)}</b> ${k.client ? `<span class="chip">${esc(k.client)}</span>` : ''}
          ${k.stale ? '<span class="pill warn">sem uso há 60+ dias</span>' : ''}
          <div class="mute small">${(k.agents || []).length ? esc(k.agents.join(', ')) : esc((k.scopes || []).join(', '))} · último uso: ${k.last_used_at ? when(k.last_used_at) : 'nunca'}</div></span>
          <button class="ghost key-rv" data-id="${k.id}" data-n="${esc(k.name)}">Revogar</button></div>`).join('')
        : '<div class="mute small mt">Nenhuma chave ativa.</div>'}</div>
  </div>

  <div class="grid g2 mt">
    <div class="card"><h2>Memória dos agentes</h2>
      <div class="mute small">Agentes com memória lembram fatos entre conversas (clientes, decisões, preferências). Você pode ver o que foi guardado e pedir a exclusão.</div>
      ${h.memory.length ? h.memory.map(m => `<div class="row between li"><a href="#/agents/${esc(m.slug)}/memory">${esc(m.name)}</a>
        <span class="chip">${esc({ agent: 'só o agente', team: 'time', org: 'empresa' }[m.scope] || m.scope)}</span></div>`).join('')
        : '<div class="mute small mt">Nenhum dos seus agentes usa memória.</div>'}</div>

    <div class="card"><div class="row between"><h2>No catálogo da empresa</h2><a href="#/agents/catalog" class="small">Ver catálogo →</a></div>
      ${h.catalog_news.length ? h.catalog_news.map(a => `<div class="row between li"><span><a href="#/agents/${esc(a.slug)}"><b>${esc(a.name)}</b></a>
          <div class="mute small one-line" data-noi18n style="max-width:360px" title="${esc(a.objective)}">${esc(a.team || '')} · ${esc(a.objective)}</div></span>
          ${a.access === 'viewer' ? `<button class="ghost ar-go" data-s="${esc(a.slug)}">Pedir acesso</button>` : '<span class="pill info">pode usar</span>'}</div>`).join('')
        : '<div class="mute small">Nenhum agente de outros times publicado para você ainda.</div>'}</div>
  </div>`;

  main.querySelectorAll('.ar-go').forEach(b => b.onclick = () => requestAccessDialog(b.dataset.s));
  main.querySelectorAll('.key-rv').forEach(b => b.onclick = e => confirm(`Revogar a chave "${b.dataset.n}"? A ferramenta que usa essa chave para de funcionar.`) &&
    act(e.target, () => api(`/keys/${b.dataset.id}`, { method: 'DELETE' }).then(homePage), 'Chave revogada'));
}

function homeAgentCard(a) {
  const env = `<span class="dot ${a.stage ? 'on' : ''}"></span>stage &nbsp;<span class="dot ${a.prod ? 'on' : ''}"></span>prod${a.prod_version ? ` v${a.prod_version}` : ''}`;
  return `<div class="card agent-card">
    <div class="row between"><a href="#/agents/${esc(a.slug)}"><b>${esc(a.name)}</b></a>${pill(a.status)}</div>
    <div class="mute small one-line" data-noi18n title="${esc(a.objective)}">${esc(a.objective)}</div>
    <div class="small mt">${env}</div>
    <div class="row small mt" style="gap:6px;flex-wrap:wrap">${a.team ? `<span class="chip">${icon('team')}${esc(a.team)}</span>` : ''}
      <span class="pill">${esc(HOME_ACCESS[a.access] || a.access || '')}</span>
      ${a.memory ? '<span class="pill info">memória</span>' : ''}${a.harness ? '<span class="pill warn">harness</span>' : ''}
      ${a.last_test === 'failed' ? '<span class="pill bad">teste reprovado</span>' : ''}
      ${a.errors_24h ? `<span class="pill bad">${a.errors_24h} erro(s) 24h</span>` : ''}</div>
    ${a.requests_7d != null ? `<div class="mute small mt">${fmt(a.requests_7d)} chamadas · ${usd(a.cost_7d)} em 7 dias</div>` : ''}
    <div class="row mt" style="gap:6px">${a.can_consume ? `<a href="#/agents/${esc(a.slug)}/playground"><button class="ghost">Testar</button></a>
      <a href="#/agents/${esc(a.slug)}/connect"><button class="ghost">Conectar</button></a>` : ''}
      ${a.can_edit ? `<a href="#/agents/${esc(a.slug)}/spec"><button class="ghost">Editar</button></a>` : ''}</div></div>`;
}
