/* ---------- Marketplace: os Digital employees já admitidos, prontos para a pessoa usar ----------
   Duas telas. A vitrine (#/market): busca, filtro por time e os cartões com rosto, cargo e o que cada um resolve.
   A página do agente (#/market/<slug>): o que pedir a ele, o que ele faz, com o que funciona e o que a cópia leva.
   "Usar este agente" contrata uma cópia pessoal (POST /api/market/<slug>/use): o original nunca é alterado. */
const MK = { q: '', team: '', sort: 'recent', list: [] };  // o filtro fica na memória: voltar da página do agente não o perde
const MK_SHOWN = 3;  // sistemas no cartão; o resto vira "+N"

const mkNorm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

function mkSystems(list, max) {
  const shown = max ? list.slice(0, max) : list;
  return `${shown.map(s => `<span class="chip" data-noi18n>${esc(s)}</span>`).join('')}${
    list.length > shown.length ? `<span class="chip" data-noi18n>+${list.length - shown.length}</span>` : ''}`;
}

function mkCard(e) {
  return `<li><a class="card mk-card" href="#/market/${esc(e.slug)}">
    <span class="mk-top">${agentAvatar(e, 'mk')}<span class="mk-id">
      ${e.team ? `<span class="mk-team" data-noi18n>${esc(e.team)}</span>` : ''}
      <span class="mk-name" data-noi18n>${esc(e.name)}</span>
      <span class="mk-title" data-noi18n>${esc(e.title)}</span></span></span>
    <span class="mk-mission" data-noi18n>${esc(e.mission)}</span>
    <span class="mk-foot">${mkSystems(e.systems || [], MK_SHOWN)}${e.mine ? '<span class="pill info">você gerencia</span>' : ''}</span></a></li>`;
}

function mkFiltered() {
  const words = mkNorm(MK.q).split(/\s+/).filter(Boolean);  // todas as palavras, em qualquer ordem ("crm vendas")
  const out = MK.list.filter(e => {
    if (MK.team && e.team !== MK.team) return false;
    const text = mkNorm([e.name, e.title, e.mission, e.team, ...(e.systems || [])].join(' '));
    return words.every(w => text.includes(w));
  });
  if (MK.sort === 'name') out.sort((a, b) => a.name.localeCompare(b.name, window.LOCALE));
  return out;
}

function mkDraw() {  // só a grade e a contagem: o campo de busca mantém o foco enquanto a pessoa digita
  const list = mkFiltered();
  $('#mk-count').innerHTML = `<b>${list.length}</b> <span>${list.length === 1 ? 'agente encontrado' : 'agentes encontrados'}</span>`;
  $('#mk-grid').innerHTML = list.length ? `<ul class="mk-grid">${list.map(mkCard).join('')}</ul>`
    : `<div class="card empty"><h2>Nenhum agente com esse filtro</h2>
        <div class="mute">Tente outra palavra ou veja todos os times.</div>
        <div class="mt"><button class="ghost" id="mk-clear">Limpar filtros</button></div></div>`;
  const clear = $('#mk-clear');
  if (clear) clear.onclick = () => { MK.q = ''; MK.team = ''; marketPage(); };
}

async function marketPage() {
  MK.list = await api('/market');
  const teams = [...new Set(MK.list.map(e => e.team).filter(Boolean))].sort((a, b) => a.localeCompare(b, window.LOCALE));
  if (MK.team && !teams.includes(MK.team)) MK.team = '';
  const chip = (value, label, noi18n) => `<button type="button" class="mk-chip" data-team="${esc(value)}" aria-pressed="${MK.team === value}"${
    noi18n ? ' data-noi18n' : ''}>${esc(label)}</button>`;
  main.innerHTML = `<div class="mk-hero">
      <h1>Agentes prontos para trabalhar com você</h1>
      <p class="sub">Escolha um Digital employee que o seu time já aprovou e receba uma cópia só sua. Você leva o cargo e as instruções; nunca as conversas, a memória ou as contas dele.</p>
      ${MK.list.length ? `<label class="mk-search">${icon('search')}<span class="sr-only">Buscar agentes</span>
        <input id="mk-q" type="search" placeholder="Buscar por nome, cargo ou sistema" value="${esc(MK.q)}" autocomplete="off"></label>` : ''}
    </div>
    ${!MK.list.length ? `<div class="card empty"><h2>O marketplace ainda está vazio</h2>
        <div class="mute">Um Digital employee aparece aqui depois de passar pelo período de experiência e ser admitido.</div>
        <div class="mt"><a href="#/employees/new?personal=1"><button>Criar um agente do zero</button></a></div></div>`
    : `${teams.length > 1 ? `<div class="mk-chips" role="group" aria-label="Filtrar por time">${chip('', 'Todos')}${teams.map(t => chip(t, t, true)).join('')}</div>` : ''}
      <div class="row between mk-bar"><div id="mk-count" class="mute small" role="status"></div>
        <div class="seg" role="group" aria-label="Ordenar"><button type="button" class="ghost ${MK.sort === 'recent' ? 'on' : ''}" data-sort="recent" aria-pressed="${MK.sort === 'recent'}">Recentes</button><button type="button" class="ghost ${MK.sort === 'name' ? 'on' : ''}" data-sort="name" aria-pressed="${MK.sort === 'name'}">A–Z</button></div></div>
      <div id="mk-grid"></div>`}`;
  if (!MK.list.length) return;
  mkDraw();
  $('#mk-q').oninput = ev => { MK.q = ev.target.value; mkDraw(); };
  main.querySelectorAll('.mk-chip').forEach(b => b.onclick = () => {
    MK.team = b.dataset.team;
    main.querySelectorAll('.mk-chip').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    mkDraw();
  });
  main.querySelectorAll('[data-sort]').forEach(b => b.onclick = () => {
    MK.sort = b.dataset.sort;
    if (MK.sort === 'recent') { marketPage(); return; }  // a ordem do servidor (admissão mais recente primeiro)
    main.querySelectorAll('[data-sort]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); });
    mkDraw();
  });
}

/* o que a cópia leva, o que não leva e como ela começa: as três perguntas de quem vai clicar em "Usar" */
function mkTakes(e) {
  const row = (ok, title, text) => `<li class="${ok ? 'yes' : 'no'}">${icon(ok ? 'check' : 'x')}<span><b>${title}</b><span class="mute small">${text}</span></span></li>`;
  return `<ul class="mk-takes">
    ${row(true, 'O cargo', 'Missão, responsabilidades, sistemas e as tarefas de experiência.')}
    ${e.copy.full ? row(true, 'Instruções, skills e apps', 'Como o original trabalha hoje, na versão em produção.')
      : row(true, 'Instruções novas', 'Escritas a partir do cargo. As do original ficam com o time dele.')}
    ${row(true, 'Aprovação antes de agir', 'A cópia começa em modo sombra e pede o seu OK no que muda algo.')}
    ${row(false, 'Conversas, tarefas e memória', 'O que o original já fez e aprendeu continua só com ele.')}
    ${row(false, 'Contas conectadas', 'Você conecta as suas.')}</ul>`;
}

async function marketDetail(slug) {
  const e = await api('/market/' + encodeURIComponent(slug));
  const words = (e.instructions || '').trim().split(/\s+/).filter(Boolean).length;
  const works = [...(e.systems || []), ...(e.apps || []).filter(a => !(e.systems || []).includes(a))];
  main.innerHTML = `<a href="#/market" class="mute small">← Marketplace</a>
    <div class="mk-head">${agentAvatar(e, 'lg')}<div>
      ${e.team ? `<div class="mk-team" data-noi18n>${esc(e.team)}</div>` : ''}
      <h1 data-noi18n>${esc(e.name)}</h1><div class="mk-role" data-noi18n>${esc(e.title)}</div></div></div>
    <p class="mk-lead" data-noi18n>${esc(e.mission)}</p>
    <div class="mk-page">
      <aside class="mk-side" aria-label="Usar este agente">
        <div class="card">
          ${e.copy.allowed ? `<button id="mk-use" class="mk-cta">${icon('copy')}Usar este agente</button>
            <p class="mute small">Você recebe uma cópia só sua. Ela pede a sua aprovação antes de agir.</p>`
          : `<p><b>Você não pode criar a cópia agora.</b></p><p class="mute small" data-noi18n>${esc(e.copy.reason)}</p>`}
          ${e.mine ? `<a href="#/employees/${esc(e.slug)}" class="small">Abrir o original (você gerencia) →</a>` : ''}
          <div id="mk-out"></div></div>
        ${works.length ? `<section aria-labelledby="mk-h-works"><h2 id="mk-h-works">Funciona com</h2><div class="mk-works">${mkSystems(works)}</div></section>` : ''}
        ${(e.skills || []).length ? `<section aria-labelledby="mk-h-skills"><h2 id="mk-h-skills">Skills</h2><div class="mk-works">${mkSystems(e.skills)}</div></section>` : ''}
        <section aria-labelledby="mk-h-takes"><h2 id="mk-h-takes">O que você leva</h2>${mkTakes(e)}</section>
      </aside>
      <div class="mk-main">
        ${(e.examples || []).length ? `<section aria-labelledby="mk-h-ask"><h2 id="mk-h-ask">Peça a ele</h2>
          <ul class="mk-asks">${e.examples.map(x => `<li data-noi18n>“${esc(x)}”</li>`).join('')}</ul></section>` : ''}
        <section aria-labelledby="mk-h-does"><h2 id="mk-h-does">O que ele faz</h2>
          <ul class="mk-resp" data-noi18n>${(e.responsibilities || []).map(r => `<li>${esc(r)}</li>`).join('')}</ul></section>
        ${e.instructions ? `<section aria-labelledby="mk-h-instr"><div class="row between"><div><h2 id="mk-h-instr">Instruções</h2>
            <div class="mute small"><span data-noi18n>${fmt(words)}</span> <span>palavras</span> · <span data-noi18n>${Math.max(1, Math.round(words / 200))}</span> <span>min de leitura</span></div></div>
            <button class="ghost" id="mk-copy">${icon('copy')}Copiar instruções</button></div>
          <div class="card md mk-instr">${mdLite(e.instructions)}</div></section>` : ''}
      </div>
    </div>`;
  const copy = $('#mk-copy');
  if (copy) copy.onclick = () => navigator.clipboard.writeText(e.instructions).then(() => toast('Copiado'));
  const use = $('#mk-use');
  if (use) use.onclick = ev => act(ev.currentTarget, async () => {
    const r = await api(`/market/${encodeURIComponent(slug)}/use`, { method: 'POST' });
    if (r.created) {
      toast('Cópia criada — comece o período de experiência');
      location.hash = `#/employees/${r.employee.slug}`;
      return;
    }
    $('#mk-out').innerHTML = `<div class="card warn-card mt" role="alert"><b>Faltam dados no cargo original para copiar:</b>
      <ul class="small">${(r.missing || []).map(m => `<li data-noi18n>${esc(m.question)}</li>`).join('')}</ul>
      <a href="#/employees/new?personal=1" class="small">Criar pelo formulário →</a></div>`;
  });
}
