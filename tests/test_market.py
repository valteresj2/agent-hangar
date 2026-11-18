"""Marketplace de Digital employees: a vitrine só mostra os admitidos que a pessoa pode ver, a página não entrega o
trabalho do original, e "usar" contrata uma cópia pessoal sem tocar nele."""
from app import services as svc
from app.db import SessionLocal

from .conftest import ADMIN
from .test_composer import _snapshot, _to_prod
from .test_employees import env, hire, make_active, rt  # noqa: F401  (fixtures)


def _slugs(client, headers):
    r = client.get("/api/market", headers=headers)
    assert r.status_code == 200, r.text
    return [e["slug"] for e in r.json()]


def test_only_admitted_employees_are_listed(client, env, rt):  # noqa: F811
    slug = hire(client, env)
    assert slug not in _slugs(client, env["h"]["req"]), "em experiência ainda não é oferta"
    assert client.get(f"/api/market/{slug}", headers=env["h"]["req"]).status_code == 403
    make_active(client, env, slug, rt)
    card = next(e for e in client.get("/api/market", headers=env["h"]["req"]).json() if e["slug"] == slug)
    assert card["title"] == "Analista de renovações" and card["systems"] == ["CRM", "e-mail"]
    assert card["team"].startswith("Sales ") and card["mine"] is False
    assert next(e for e in client.get("/api/market", headers=env["h"]["mgr"]).json() if e["slug"] == slug)["mine"] is True
    assert slug in _slugs(client, env["h"]["out"]), "visível na empresa: o outro time também o encontra"


def test_detail_shows_the_job_and_never_the_work(client, env, rt):  # noqa: F811
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    d = client.get(f"/api/market/{slug}", headers=env["h"]["req"]).json()
    assert d["copy"]["full"] is False and d["instructions"] is None, "sem versão em produção não há base para copiar"
    _to_prod(slug)
    d = client.get(f"/api/market/{slug}", headers=env["h"]["req"]).json()
    assert d["responsibilities"] == ["acompanhar renovações", "preparar propostas", "avisar riscos"]
    assert d["examples"] == ["Tarefa 0", "Tarefa 1", "Tarefa 2"]
    assert d["copy"] == {"allowed": True, "reason": "", "full": True}  # developer do time vê a spec
    assert "Analista de renovações" in d["instructions"]
    for private in ("lessons", "tasks", "cost_30d", "metrics", "probation", "rules", "manager"):
        assert private not in d


def test_use_hires_a_personal_copy_and_leaves_the_original_alone(client, env, rt):  # noqa: F811
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    _to_prod(slug)
    before = client.get(f"/api/employees/{slug}", headers=env["h"]["own"]).json()
    snap = _snapshot(slug)
    r = client.post(f"/api/market/{slug}/use", headers=env["h"]["req"])
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True, r.json()
    copy = r.json()["employee"]
    assert copy["slug"] != slug and copy["title"] == before["title"] and copy["mission"] == before["mission"]
    assert copy["personal"] is True and copy["shadow"] is True and copy["status"] == "onboarding"
    assert copy["manager"] and copy["can_manage"] is True, "quem copiou é o gestor da cópia"
    assert [t["title"] for t in copy["probation"]] == ["Tarefa 0", "Tarefa 1", "Tarefa 2"]
    # as instruções vêm da base uma vez só (o cargo não é escrito de novo por cima)
    with SessionLocal() as db:
        text = svc.spec_of(svc.get_agent(db, copy["slug"])).get("instructions", "")
    assert text.count("Cargo: Analista de renovações") == 1, text
    lineage = client.get(f"/api/agents/{copy['slug']}/lineage", headers=ADMIN).json()
    assert lineage["built_from"]["based_on"]["slug"] == slug
    # a cópia é pessoal: não vira oferta nem aparece para o resto do time
    assert copy["slug"] not in _slugs(client, env["h"]["own"])
    # o original segue igual
    after = client.get(f"/api/employees/{slug}", headers=env["h"]["own"]).json()
    assert after["status"] == "active" and after["responsibilities"] == before["responsibilities"]
    assert _snapshot(slug) == snap


def test_another_team_copies_the_job_without_the_spec(client, env, rt):  # noqa: F811
    """Quem só vê o agente (outro time) não lê as instruções do original: a cópia leva o cargo e ganha instruções
    novas, sem a base."""
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    _to_prod(slug)
    d = client.get(f"/api/market/{slug}", headers=env["h"]["out"]).json()
    assert d["instructions"] is None and d["skills"] == [] and d["apps"] == []
    assert d["copy"] == {"allowed": True, "reason": "", "full": False}
    r = client.post(f"/api/market/{slug}/use", headers=env["h"]["out"])
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True, r.json()
    copy = r.json()["employee"]
    assert copy["personal"] is True and copy["title"] == "Analista de renovações"
    lineage = client.get(f"/api/agents/{copy['slug']}/lineage", headers=ADMIN).json()
    assert not (lineage["built_from"] or {}).get("based_on"), "sem permissão de spec, nada do original é copiado"


def test_unknown_agent_is_not_found(client, env):  # noqa: F811
    assert client.get("/api/market/nao-existe", headers=env["h"]["req"]).status_code in (400, 403, 404)
    assert client.post("/api/market/nao-existe/use", headers=env["h"]["req"]).status_code in (400, 403, 404)
