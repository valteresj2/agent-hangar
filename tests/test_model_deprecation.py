"""Modelos que o provedor vai descontinuar: a data da tabela pública e a do admin, quem usa (llm, harness, juiz, modelo
por resposta, por ambiente), o substituto, a troca em versão nova, os avisos por faixa na caixa de entrada, a
ferramenta do MCP e a recomendação de modelos que deixa de lado quem vai sair."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import services as svc
from app.db import SessionLocal
from app.models import now
from app.services import llm_models as lm
from app.services import model_deprecation as md

from .conftest import ADMIN
from .test_access import _mcp

TODAY = now().date()
SOON, LATER = TODAY + timedelta(days=20), TODAY + timedelta(days=400)
OPENAI = {"data": [{"id": x} for x in ("gpt-4o-2024-05-13", "gpt-4o-2024-11-20", "gpt-4.1-mini", "o3-vision",
                                        "text-embedding-3-small")]}
CATALOG = {
    "gpt-4o-2024-05-13": {"mode": "chat", "supports_function_calling": True, "max_input_tokens": 128000,
                          "deprecation_date": SOON.isoformat(), "input_cost_per_token": 5e-6, "output_cost_per_token": 1.5e-5},
    "gpt-4o-2024-11-20": {"mode": "chat", "supports_function_calling": True, "max_input_tokens": 128000,
                          "deprecation_date": LATER.isoformat(), "input_cost_per_token": 2.5e-6, "output_cost_per_token": 1e-5},
    "gpt-4.1-mini": {"mode": "chat", "supports_function_calling": True, "max_input_tokens": 1000000},
    "o3-vision": {"mode": "chat", "max_input_tokens": 200000},  # sem ferramentas: não serve de substituto
    "text-embedding-3-small": {"mode": "embedding", "deprecation_date": "bad-date"},
}


@pytest.fixture(autouse=True)
def _dates():
    """As datas são as do momento do teste, não as da importação: a suíte pode cruzar a meia-noite (UTC)."""
    global TODAY, SOON, LATER
    TODAY = now().date()
    SOON, LATER = TODAY + timedelta(days=20), TODAY + timedelta(days=400)
    CATALOG["gpt-4o-2024-05-13"]["deprecation_date"] = SOON.isoformat()
    CATALOG["gpt-4o-2024-11-20"]["deprecation_date"] = LATER.isoformat()


@pytest.fixture()
def provider(client, uniq, monkeypatch):
    """Uma conexão OpenAI com a lista falsa e a tabela pública falsa; devolve o nome."""
    monkeypatch.setattr(lm, "_get", lambda url, headers, params=None: OPENAI)
    monkeypatch.setattr(lm, "public_catalog", lambda: CATALOG)
    md.forget()
    name = uniq("oa")
    r = client.post("/api/catalog/llm", headers=ADMIN, json={"name": name, "provider": "openai", "api_key": "k",
                                                              "base_url": "https://api.openai.com/v1", "model_name": "gpt-4.1-mini"})
    assert r.status_code == 200, r.text
    yield name
    md.forget()


def _models(client, name):
    return {m["id"]: m for m in client.get(f"/api/catalog/models?connection={name}&all=true", headers=ADMIN).json()}


def _agent(client, uniq, spec):
    slug = client.post("/api/agents", headers=ADMIN, json={"name": uniq("ag"), "objective": "o", "final_output": "f"}).json()["slug"]
    r = client.patch(f"/api/agents/{slug}", headers=ADMIN, json=spec)
    assert r.status_code == 200, r.text
    return slug


def test_stages_and_wording():
    assert [md.stage_of(n) for n in (90, 60, 45, 30, 20, 14, 10, 7, 3, 1, 0, -5)] == [60, 60, 60, 30, 30, 14, 14, 7, 7, 1, 0, 0]
    assert md.when_text(TODAY + timedelta(days=9)).endswith("(em 9 dias)")
    assert "amanhã" in md.when_text(TODAY + timedelta(days=1)) and "hoje" in md.when_text(TODAY)
    assert md.when_text(TODAY - timedelta(days=3)).startswith("saiu do provedor em")
    assert lm.deprecation_of({"deprecation_date": "2027-01-31"}).isoformat() == "2027-01-31"
    assert lm.deprecation_of({"deprecation_date": "nope"}) is None and lm.deprecation_of(None) is None


def test_sync_fills_the_date_and_the_admin_override_sticks(client, provider):
    ms = _models(client, provider)
    leaving = ms["gpt-4o-2024-05-13"]
    assert (leaving["deprecates_on"], leaving["deprecation_source"], leaving["days_left"]) == (SOON.isoformat(), "catalog", 20)
    assert ms["gpt-4.1-mini"]["deprecates_on"] is None and ms["text-embedding-3-small"]["deprecates_on"] is None  # data inválida
    url = f"/api/catalog/llm/{provider}/models/gpt-4.1-mini"
    r = client.patch(url, headers=ADMIN, json={"deprecates_on": (TODAY + timedelta(days=5)).isoformat()})
    assert r.status_code == 200 and r.json()["deprecation_source"] == "admin"
    client.post(f"/api/catalog/llm/{provider}/models/sync", headers=ADMIN)
    assert _models(client, provider)["gpt-4.1-mini"]["days_left"] == 5  # a coleta não desfaz o que o admin informou
    assert client.patch(url, headers=ADMIN, json={"deprecates_on": "31/12/2027"}).status_code == 400
    back = client.patch(url, headers=ADMIN, json={"deprecates_on": ""}).json()
    assert (back["deprecates_on"], back["deprecation_source"]) == (None, "")  # volta à tabela pública (sem data)


def test_who_uses_it_replacement_and_the_admin_list(client, uniq, provider):
    slug = _agent(client, uniq, {"llm": {"connection": provider, "model": "gpt-4o-2024-05-13"}})
    r = client.get(f"/api/agents/{slug}/model-deprecation", headers=ADMIN).json()
    x = r["models"][0]
    assert (x["model"], x["soon"], x["where"], x["envs"]) == ("gpt-4o-2024-05-13", True, ["llm"], ["prod", "stage"])
    assert x["replacement"]["model"] == "gpt-4o-2024-11-20"  # mesma família, mais novo, com ferramentas, saída distante
    assert "mesma família" in x["replacement"]["reasons"] and x["changes"] == {"llm": {"model": "gpt-4o-2024-11-20"}}
    lst = client.get("/api/catalog/models/deprecations", headers=ADMIN).json()
    row = next(m for m in lst["models"] if m["connection"] == provider)
    assert row["in_use"] and [u["agent"] for u in row["agents"]] == [slug] and row["stage"] == 30
    assert all(m["model"] != "gpt-4o-2024-11-20" for m in lst["models"] if m["connection"] == provider)  # saída distante
    later = client.get("/api/catalog/models/deprecations?all=true", headers=ADMIN).json()["models"]
    assert any(m["model"] == "gpt-4o-2024-11-20" for m in later)


def test_swap_creates_a_new_version_and_production_keeps_the_old(client, uniq, provider):
    slug = _agent(client, uniq, {"llm": {"connection": provider, "model": "gpt-4o-2024-05-13"},
                                 "execution": {"light_model": "gpt-4o-2024-05-13"}})
    before = client.get(f"/api/agents/{slug}", headers=ADMIN).json()["version"]
    r = client.post(f"/api/agents/{slug}/model-deprecation/swap", headers=ADMIN,
                    json={"connection": provider, "model": "gpt-4o-2024-05-13", "test": False})
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["from"], out["to"], out["version"]) == ("gpt-4o-2024-05-13", "gpt-4o-2024-11-20", before + 1)
    with SessionLocal() as db:
        spec = svc.spec_of(svc.get_agent(db, slug))
    assert spec["llm"]["model"] == "gpt-4o-2024-11-20" and spec["execution"]["light_model"] == "gpt-4o-2024-11-20"
    assert client.get(f"/api/agents/{slug}/model-deprecation", headers=ADMIN).json()["models"][0]["soon"] is False
    bad = client.post(f"/api/agents/{slug}/model-deprecation/swap", headers=ADMIN,
                      json={"connection": provider, "model": "gpt-4.1-mini"})
    assert bad.status_code == 400


def test_change_for_covers_overrides_harness_and_judge():
    conns = {"c": SimpleNamespace(model_name="old"), "d": SimpleNamespace(model_name="x")}
    spec = {"llm": {"connection": "c", "model": "", "prod": {"model": "old"}, "stage": {"connection": "d"}},
            "harness": {"id": "claude-code", "connection": "c", "model": "keep", "stage": {"model": "old"}},
            "judge": {"connection": "c", "model": "old"}, "execution": {"light_model": "auto"}}
    assert md.change_for(spec, conns, "c", "old", "new") == {
        "llm": {"model": "new", "prod": {"model": "new"}}, "harness": {"stage": {"model": "new"}},
        "judge": {"model": "new"}}
    uses = md.uses_of(spec, conns)
    assert ("c", "old", "harness", "stage") in uses and ("d", "x", "llm", "stage") in uses
    assert not any(u[2] == "light_model" for u in uses)  # 'auto' não é um modelo


def test_inbox_warns_admins_and_editors_once_per_stage(client, uniq, provider):
    slug = _agent(client, uniq, {"llm": {"connection": provider, "model": "gpt-4o-2024-05-13"}})
    with SessionLocal() as db:
        admin = SimpleNamespace(p=SimpleNamespace(is_admin=True))
        editor = SimpleNamespace(p=SimpleNamespace(is_admin=False), can=lambda action, a: a.slug == slug)
        outsider = SimpleNamespace(p=SimpleNamespace(is_admin=False), can=lambda action, a: False)
        md.forget()
        a_items = [x for x in md.inbox_items(db, admin) if provider in x["title"]]
        e_items = [x for x in md.inbox_items(db, editor) if x["data"].get("agent") == slug]
        assert len(a_items) == 1 and a_items[0]["key"].endswith(":30") and len(a_items[0]["key"]) <= 40
        assert "gpt-4o-2024-11-20" in a_items[0]["title"] and not a_items[0]["blocked"]
        assert len(e_items) == 1 and e_items[0]["link"] == f"#/agents/{slug}" and len(e_items[0]["key"]) <= 40
        assert not [x for x in md.inbox_items(db, outsider) if x["data"].get("agent") == slug]
        assert a_items[0]["at"] == md.stage_started(SOON, 30)  # data estável: ler não faz o aviso voltar


def test_mcp_lists_and_warns_when_building(client, uniq, provider):
    slug = _agent(client, uniq, {"llm": {"connection": provider, "model": "gpt-4.1-mini"}})
    r = json.loads(_mcp(client, ADMIN, "design_agent", {"slug": slug, "model": "gpt-4o-2024-05-13"})["content"][0]["text"])
    assert r["model_warnings"] and "gpt-4o-2024-11-20" in r["model_warnings"][0]
    lst = json.loads(_mcp(client, ADMIN, "list_model_deprecations", {})["content"][0]["text"])
    mine = [x for x in lst["agents"] if x["agent"] == slug]
    assert mine and mine[0]["changes"] == {"llm": {"model": "gpt-4o-2024-11-20"}}
    assert any(m["connection"] == provider for m in lst["models"])


def test_recommendations_skip_models_leaving_soon(client, provider):
    with SessionLocal() as db:
        ids = {m.model_id for m, c in svc.model_selection.context(db)["rows"] if c.name == provider}
    assert "gpt-4o-2024-05-13" not in ids and {"gpt-4o-2024-11-20", "gpt-4.1-mini"} <= ids


def test_migration_adds_and_drops_the_columns(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from app import db as dbmod
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    cfg = dbmod._alembic_config()
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    try:
        cols = lambda: {c["name"] for c in inspect(eng).get_columns("llm_models")}  # noqa: E731
        assert {"deprecates_on", "deprecation_source"} <= cols()
        command.downgrade(cfg, "0054_app_events")
        assert "deprecates_on" not in cols()
        command.upgrade(cfg, "head")
    finally:
        eng.dispose()
