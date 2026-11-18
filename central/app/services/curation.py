"""Curadoria noturna da memória do Digital employee ("dreaming"): uma revisão por dia do que ele aprendeu.

As lições (`Employee.lessons`, até 20) entram no prompt de toda tarefa nova. Com o tempo elas se repetem, ficam velhas
ou se contradizem, e o que as pessoas corrigem tarefa a tarefa nem sempre vira lição. Uma vez por dia, de madrugada
(fuso da empresa), para cada funcionário ativo com aprendizado ligado e com trabalho novo desde a última revisão, a
plataforma olha o período e **propõe**:

- `merge`: juntar lições repetidas numa só;
- `rewrite`: reescrever uma lição que o trabalho recente mostrou estar incompleta ou errada;
- `remove`: retirar uma lição que não vale mais;
- `new`: uma lição nova, a partir de um padrão que apareceu em mais de uma tarefa (correções, mensagens das pessoas,
  notas de qualidade, falhas).

Nada muda sozinho: as propostas aparecem junto das outras sugestões de aprendizado (aba Alçada), e o gestor aplica,
edita ou dispensa. Com o modelo do funcionário, a revisão é feita por ele (uma chamada por dia, só quando há trabalho
novo); sem modelo, a regra acha só as lições repetidas.

A memória em grafo (quando ligada) não entra aqui: ela já guarda a validade de cada fato e marca o que foi substituído.
"""
import hashlib
import logging
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .. import tenancy
from ..models import Agent, Employee, EmployeeTask, HumanRequest, Organization, TaskMessage, now
from . import employee_tasks as tasksmod
from .common import PlatformError, audit, iso

HOUR = 3  # de madrugada, no fuso da empresa
WINDOW = timedelta(days=7)  # no máximo, o que olha para trás
MAX_ITEMS = 5
ACTIONS = ("merge", "rewrite", "remove", "new")
_last_run: dict[int, str] = {}
log = logging.getLogger("hangar.curation")

PROMPT = {
    "pt": ("Você faz a curadoria das lições de um funcionário digital: regras curtas que entram no prompt de toda tarefa "
           "dele. Olhe as lições atuais e o trabalho do período (tarefas, correções do gestor, mensagens das pessoas, "
           "notas de qualidade, falhas) e proponha no máximo {n} mudanças, só com evidência:\n"
           "- merge: lições repetidas viram uma (lessons: os ids, text: a lição única);\n"
           "- rewrite: uma lição que o trabalho mostrou estar incompleta ou errada (lessons: [id], text: a nova);\n"
           "- remove: uma lição que não vale mais (lessons: [id], text vazio);\n"
           "- new: um padrão que apareceu em DUAS ou mais tarefas ou correções e ainda não é lição (lessons: [], text).\n"
           "Lição: uma ou duas frases no imperativo, até 400 caracteres, sem nomes de pessoas, números de documentos ou "
           "dados de clientes. Nada de óbvio ou genérico. Se não houver nada a mudar, devolva items vazio. Responda só "
           'com JSON: {{"items": [{{"action": "...", "lessons": ["id"], "text": "...", "why": "o porquê, citando as '
           'tarefas", "tasks": [123]}}]}}'),
    "en": ("You curate the lessons of a digital employee: short rules that go into the prompt of every task it gets. "
           "Look at the current lessons and the period's work (tasks, the manager's corrections, people's messages, "
           "quality notes, failures) and propose at most {n} changes, only with evidence:\n"
           "- merge: repeated lessons become one (lessons: the ids, text: the single lesson);\n"
           "- rewrite: a lesson the work showed to be incomplete or wrong (lessons: [id], text: the new one);\n"
           "- remove: a lesson that no longer holds (lessons: [id], empty text);\n"
           "- new: a pattern seen in TWO or more tasks or corrections that isn't a lesson yet (lessons: [], text).\n"
           "Lesson: one or two imperative sentences, up to 400 characters, no people's names, document numbers or "
           "customer data. Nothing obvious or generic. If there is nothing to change, return empty items. Answer only "
           'with JSON: {{"items": [{{"action": "...", "lessons": ["id"], "text": "...", "why": "the reason, citing the '
           'tasks", "tasks": [123]}}]}}'),
}
HEAD = {
    "pt": {"merge": "Juntar {k} lições repetidas numa só", "rewrite": "Reescrever uma lição", "remove": "Retirar uma lição",
           "new": "Nova lição a partir de um padrão do trabalho"},
    "en": {"merge": "Merge {k} repeated lessons into one", "rewrite": "Rewrite a lesson", "remove": "Remove a lesson",
           "new": "New lesson from a pattern in the work"},
}


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", (t or "").casefold()).strip()


def evidence(db, e: Employee, since) -> dict:
    """O trabalho do período, compacto: tarefas, correções, mensagens das pessoas."""
    tasks = db.scalars(select(EmployeeTask).where(EmployeeTask.employee_id == e.id, EmployeeTask.probation.is_(False),
                                                  EmployeeTask.finished_at.is_not(None), EmployeeTask.finished_at >= since,
                                                  EmployeeTask.status.in_(("done", "failed")))
                       .order_by(EmployeeTask.id.desc()).limit(30)).all()
    corr = db.scalars(select(HumanRequest).where(
        HumanRequest.employee_id == e.id, HumanRequest.status == "decided", HumanRequest.decided_at >= since,
        HumanRequest.decision.in_(("approve_edited", "reject", "instruct", "disagree")))
        .order_by(HumanRequest.id.desc()).limit(30)).all()
    ids = [t.id for t in tasks]
    msgs = db.scalars(select(TaskMessage).where(TaskMessage.task_id.in_(ids), TaskMessage.user_id.is_not(None))
                      .order_by(TaskMessage.id.desc()).limit(30)).all() if ids else []
    return {"tasks": tasks, "corrections": corr, "messages": msgs}


def _brief(e: Employee, ev: dict) -> str:
    from .employee_work import _edit_summary
    lines = ["LIÇÕES ATUAIS:"] + ([f"- [{x['id']}] {x.get('text', '')}" for x in e.lessons or []] or ["(nenhuma)"])
    lines.append("\nTAREFAS DO PERÍODO:")
    for t in ev["tasks"]:
        extra = f" · nota {t.quality}: {t.quality_note[:200]}" if t.quality is not None and t.quality <= 3 else ""
        extra += f" · erro: {t.error[:200]}" if t.status == "failed" and t.error else ""
        lines.append(f"- #{t.id} {t.title[:120]} ({t.status}){extra}")
    lines.append("\nCORREÇÕES DO GESTOR:")
    for r in ev["corrections"]:
        why = (r.reason or "").strip() or (_edit_summary(r) if r.decision == "approve_edited" else "")
        lines.append(f"- tarefa #{r.task_id} · {r.tool_name or r.kind} · {r.decision}" + (f": {why[:300]}" if why else ""))
    lines.append("\nMENSAGENS DAS PESSOAS NAS TAREFAS:")
    for m in ev["messages"]:
        lines.append(f"- tarefa #{m.task_id}: {m.body[:300]}")
    return "\n".join(lines)


def _duplicates(e: Employee) -> list[dict]:
    """Sem modelo: as lições com o mesmo texto (ignorando maiúsculas e pontuação) viram uma proposta de juntar."""
    seen: dict[str, list[dict]] = {}
    for x in e.lessons or []:
        seen.setdefault(_norm(x.get("text", "")), []).append(x)
    return [{"action": "merge", "lessons": [x["id"] for x in group], "text": group[0]["text"],
             "why": "lições com o mesmo texto", "tasks": []} for key, group in seen.items() if key and len(group) > 1]


def _clean(e: Employee, raw: list, ev: dict) -> list[dict]:
    have = {x["id"] for x in e.lessons or []}
    known = {t.id for t in ev["tasks"]} | {r.task_id for r in ev["corrections"] if r.task_id}
    out, used = [], set()
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict) or it.get("action") not in ACTIONS:
            continue
        act = it["action"]
        ids = [str(i) for i in it.get("lessons") or [] if str(i) in have and str(i) not in used]
        text = str(it.get("text") or "").strip()[:400]
        if (act == "merge" and (len(ids) < 2 or not text)) or (act == "rewrite" and (len(ids) != 1 or not text)) \
                or (act == "remove" and not ids) or (act == "new" and (ids or not text)):
            continue
        if act == "new" and len(e.lessons or []) + sum(1 for o in out if o["action"] == "new") >= 20:
            continue  # sem espaço: no máximo 20 lições
        used.update(ids)
        tasks = [int(t) for t in it.get("tasks") or [] if str(t).isdigit() and int(t) in known][:10]
        out.append({"action": act, "lessons": ids, "text": "" if act == "remove" else text,
                    "why": str(it.get("why") or "").strip()[:600], "tasks": tasks})
        if len(out) >= MAX_ITEMS:
            break
    return out


def curate(db, e: Employee, at=None) -> list[dict]:
    """Revisa o período e guarda as propostas em Employee.curation (substituem as da revisão anterior)."""
    from . import llm
    at = at or now()
    last = (e.curation or {}).get("at")
    since = max(at - WINDOW, tasksmod._aware(_parse(last))) if last else at - WINDOW
    ev = evidence(db, e, since)
    lang = "en" if tasksmod.lang_of(e) == "en" else "pt"
    items, source = _duplicates(e), "regra"
    tgt = llm.target_for_employee(db, e)
    if tgt is not None and (ev["tasks"] or ev["corrections"] or ev["messages"] or len(e.lessons or []) > 1):
        try:
            out = llm.complete_json(tgt, PROMPT[lang].format(n=MAX_ITEMS), _brief(e, ev))
            items, source = _clean(e, (out or {}).get("items") if isinstance(out, dict) else out, ev), "modelo"
        except Exception as ex:  # noqa: BLE001 — a curadoria é ajuda: sem ela, ficam as repetidas pela regra
            log.warning("curadoria do funcionário %s: %s", e.id, ex)
    for it in items:
        it["id"] = "curate:" + hashlib.sha1(f"{it['action']}|{','.join(it['lessons'])}|{it['text']}".encode()).hexdigest()[:10]
    e.curation = {"at": iso(at), "source": source, "items": items,
                  "looked_at": {"tasks": len(ev["tasks"]), "corrections": len(ev["corrections"]),
                                "messages": len(ev["messages"])}}
    db.commit()
    return items


def _parse(s: str):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def suggestions(e: Employee, dismissed: set[str], en: bool) -> list[dict]:
    """As propostas da última revisão que ainda valem (as lições citadas existem), no formato das sugestões."""
    have = {x["id"]: x for x in e.lessons or []}
    head = HEAD["en" if en else "pt"]
    out = []
    for it in (e.curation or {}).get("items") or []:
        if it["id"] in dismissed or any(i not in have for i in it["lessons"]):
            continue
        if it["action"] == "new" and any(_norm(x.get("text", "")) == _norm(it["text"]) for x in have.values()):
            continue  # já virou lição
        out.append({"id": it["id"], "kind": "curation", "action": it["action"], "text": head[it["action"]].format(k=len(it["lessons"])),
                    "why": it["why"], "lesson": it["text"], "tasks": it["tasks"],
                    "replaces": [{"id": i, "text": have[i].get("text", "")} for i in it["lessons"]],
                    "evidence": max(len(it["tasks"]), len(it["lessons"])), "at": (e.curation or {}).get("at")})
    return out


def apply(db, acc, e: Employee, a: Agent, sug: dict, text: str = "") -> dict:
    """Aplica uma proposta: tira as lições citadas e, salvo em remove, põe a nova (ou a versão editada pelo gestor)."""
    from .employee_work import add_lesson
    new = (text or sug["lesson"] or "").strip()
    if sug["action"] != "remove" and not new:
        raise PlatformError("escreva a lição")
    gone = {x["id"] for x in sug["replaces"]}
    e.lessons = [x for x in e.lessons or [] if x.get("id") not in gone]
    db.commit()
    item = add_lesson(db, e, new, sug["id"], acc.p.name) if sug["action"] != "remove" else None
    audit(db, acc.p.name, f"employee.curation.{sug['action']}", a.slug, (new or ", ".join(sorted(gone)))[:200])
    return {"applied": sug["id"], "lesson": item, "lessons": e.lessons}


def due(db, e: Employee, at) -> bool:
    """Tem trabalho novo desde a última revisão (e ela não foi hoje)?"""
    last = (e.curation or {}).get("at")
    if last and tasksmod._aware(_parse(last)).date() == at.date():
        return False
    since = tasksmod._aware(_parse(last)) if last else at - WINDOW
    ev = evidence(db, e, since)
    return bool(ev["tasks"] or ev["corrections"])


def run_now(db, acc, slug: str) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    items = curate(db, e)
    audit(db, acc.p.name, "employee.curation.run", a.slug, f"{len(items)} proposta(s)")
    return {"curation": e.curation, "items": items}


def sweep(db, at=None) -> int:
    """Uma vez por dia, por empresa, depois das 3h no fuso dela: revisa quem tem trabalho novo."""
    at = at or now()
    org = tenancy.current_org()
    o = db.get(Organization, org)
    local = at.astimezone(ZoneInfo((o.timezone if o else None) or "UTC"))
    if local.hour < HOUR or _last_run.get(org) == local.date().isoformat():
        return 0
    _last_run[org] = local.date().isoformat()
    n = 0
    for e in db.scalars(select(Employee).where(Employee.status == "active")).all():
        if (e.learning_mode or "on") != "on" or not due(db, e, at):
            continue
        try:
            curate(db, e, at)
            n += 1
        except Exception:  # noqa: BLE001 — um funcionário com problema não para a revisão dos outros
            db.rollback()
    return n
