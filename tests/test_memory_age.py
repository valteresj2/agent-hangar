"""Memória com MEMORY_BACKEND=age (Apache AGE + pgvector no Postgres).

Sem banco: as funções do motor (nome normalizado, nome do grafo, JSON do LLM, fato atual) e o servidor com um motor
falso (a fila grava no grupo imposto pela central, recall/admin passam pelo motor, apagar o grupo apaga só ele).
Com AGE_TEST_URL (um Postgres com as extensões age e vector, ex.: a imagem mcp-servers/memory/age-postgres): o motor de
verdade, com um LLM roteirizado — fatos datados, troca de plano com histórico, repetição, nome malicioso guardado como
dado, isolamento entre grupos e apagar o grupo."""
import asyncio
import hashlib
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM = os.path.join(ROOT, "mcp-servers", "memory")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("memory_age_store", os.path.join(MEM, "app", "age_store.py"))


def test_engine_helpers():
    assert A.norm("  ACME   Ltda. ") == "acme ltda" and A.norm("Ação São Paulo") == "acao sao paulo"
    g = A.graph_name("agent-x__stage")
    assert g.startswith("hm_") and len(g) == 27 and g == A.graph_name("agent-x__stage") != A.graph_name("agent-y")
    assert A.parse_json('```json\n{"facts": []}\n```') == {"facts": []}
    with pytest.raises(ValueError):
        A.parse_json("sem json")
    now = datetime.now(UTC)
    assert A.is_current(None, None) and not A.is_current(None, now)
    assert A.is_current(now + timedelta(days=3), now)  # "em teste até…": vale até a data
    assert not A.is_current(now - timedelta(days=1), None)
    assert A._day("2026-03-01", None).isoformat() == "2026-03-01T00:00:00+00:00"
    assert A._day("março", now) == now and A._vec([1, 0.5]) == "[1,0.5]"


# ------------------------------------------------------------------ o servidor com um motor falso
@pytest.fixture()
def srv(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "age")
    monkeypatch.setenv("MEMORY_TOKEN", "t")
    mod = _load("memory_server_age", os.path.join(MEM, "app", "server.py"))
    yield mod
    sys.modules.pop("memory_server_age", None)


class FakeAge:
    def __init__(self):
        self.calls = []

    async def add(self, content, group, source, at):
        self.calls.append(("add", content, group, source, at))
        return {"facts": 1}

    async def search(self, query, groups, limit, history):
        self.calls.append(("search", query, groups, limit, history))
        f = {"id": "1", "fact": "A ACME está no Enterprise.", "valid_at": None, "invalid_at": None,
             "created_at": "2026-10-01T00:00:00+00:00", "current": True, "group": groups[0]}
        old = {**f, "id": "2", "fact": "A ACME está no Pro.", "current": False}
        return {"facts": [f, dict(f, id="1b"), old], "entities": [{"name": "ACME", "summary": "cliente", "group": groups[0]}],
                "sources": []}

    def recent(self, group, limit):
        self.calls.append(("recent", group, limit))
        return []

    def clear(self, group):
        self.calls.append(("clear", group))

    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


def test_queue_writes_to_the_group_the_central_imposes(srv):
    g = FakeAge()
    srv.S.graphiti = g
    at = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

    async def run():
        srv._enqueue({"name": "x", "content": "A ACME trocou para o Enterprise.", "source": "agente x", "at": at,
                      "group": "agent-x__stage"})
        await srv.S.queue.join()
        srv.S.worker.cancel()
    asyncio.run(run())
    assert g.calls == [("add", "A ACME trocou para o Enterprise.", "agent-x__stage", "agente x", at)]
    assert srv.S.processed == 1 and srv.S.failed == 0


def test_admin_routes_go_through_the_engine(srv):
    g = FakeAge()
    srv.S.graphiti = g
    from starlette.testclient import TestClient
    c = TestClient(srv.TokenGuard(srv.mcp.streamable_http_app()))
    h = {"Authorization": "Bearer t"}
    assert c.get("/admin/facts?group=agent-x").status_code == 401
    r = c.get("/admin/facts?group=agent-x&q=plano", headers=h).json()
    assert [f["id"] for f in r["facts"]] == ["1", "2"]  # o mesmo fato duas vezes aparece uma vez
    assert g.calls[-1] == ("search", "plano", ["agent-x"], 50, True)
    c.get("/admin/facts?group=agent-x", headers=h)
    assert g.calls[-1] == ("recent", "agent-x", 50)
    assert c.delete("/admin/groups/agent-x", headers=h).json() == {"cleared": "agent-x"} and g.calls[-1] == ("clear", "agent-x")
    assert c.post("/admin/embed", headers=h, json={"texts": ["a", "b"]}).json()["vectors"] == [[0.1, 0.2], [0.1, 0.2]]


# ------------------------------------------------------------------ o motor de verdade (AGE_TEST_URL)
AGE_URL = os.environ.get("AGE_TEST_URL", "")
DIM = 16


def _fake_vec(t: str) -> list[float]:
    v = [0.0] * DIM
    for w in A.norm(t).split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    return v


@pytest.mark.skipif(not AGE_URL, reason="AGE_TEST_URL não definido (Postgres com age e vector)")
def test_engine_on_a_real_age_database():
    script: list = []
    seen: list = []

    async def llm(system, user):
        seen.append(("resolve" if system.startswith("Para cada fato novo") else "extract", user))
        return json.dumps(script.pop(0))

    async def embed(texts):
        return [_fake_vec(t) for t in texts]

    s = A.AgeStore(AGE_URL, llm, embed, DIM)
    g, other = "agent-age-test", "agent-age-other"
    for x in (g, other):
        s.clear(x)

    async def run():
        script.append({"entities": [{"name": "ACME", "summary": "cliente"}, {"name": "plano Pro"}],
                       "facts": [{"subject": "ACME", "predicate": "tem plano", "object": "plano Pro",
                                  "fact": "A ACME está no plano Pro.", "valid_at": "2026-01-10"}]})
        r1 = await s.add("A ACME está no plano Pro desde janeiro.", g, "agente x", datetime(2026, 1, 10, tzinfo=UTC))
        assert r1["facts"] == 1 and r1["entities"] == 2
        old = (await s.search("plano da ACME", [g], 5, True))["facts"][0]
        assert old["valid_at"].startswith("2026-01-10") and old["current"]
        # troca de plano: o resolvedor recebe o fato antigo como candidato; um id inventado é ignorado
        script.append({"entities": [{"name": "Acme", "summary": "migrou"}, {"name": "plano Enterprise"}],
                       "facts": [{"subject": "Acme", "predicate": "TEM_PLANO", "object": "plano Enterprise",
                                  "fact": "A ACME está no plano Enterprise.", "valid_at": "2026-03-01"}]})
        script.append({"results": [{"new": 0, "duplicate_of": None, "replaces": [old["id"], "id-inventado"]}]})
        r2 = await s.add("A ACME migrou para o Enterprise em março.", g, "agente x", datetime(2026, 3, 1, tzinfo=UTC))
        assert r2["replaced"] == 1 and seen[-1][0] == "resolve" and old["id"] in seen[-1][1]
        cur = await s.search("plano da ACME", [g], 5, False)
        assert [f["fact"] for f in cur["facts"]] == ["A ACME está no plano Enterprise."]
        hist = {f["fact"]: f for f in (await s.search("plano da ACME", [g], 5, True))["facts"]}
        assert not hist["A ACME está no plano Pro."]["current"]
        assert hist["A ACME está no plano Pro."]["invalid_at"].startswith("2026-03-01")
        acme = next(e for e in cur["entities"] if e["name"] == "ACME")  # "Acme" é a mesma entidade
        assert "migrou" in acme["summary"] and cur["sources"][0]["text"].startswith("A ACME migrou")
        # repetição: não grava de novo
        script.append({"entities": [{"name": "ACME"}, {"name": "plano Enterprise"}],
                       "facts": [{"subject": "ACME", "predicate": "TEM_PLANO", "object": "plano Enterprise",
                                  "fact": "A ACME está no plano Enterprise."}]})
        script.append({"results": [{"new": 0, "duplicate_of": cur["facts"][0]["id"], "replaces": []}]})
        assert (await s.add("A ACME continua no Enterprise.", g, "x", datetime(2026, 4, 1, tzinfo=UTC)))["duplicates"] == 1
        # nome hostil é dado: vai como parâmetro do Cypher, não como código
        evil = "x'}) DETACH DELETE n //"
        script.append({"entities": [{"name": evil}, {"name": "Beta"}],
                       "facts": [{"subject": evil, "predicate": "CONHECE", "object": "Beta", "fact": "x conhece Beta."}]})
        await s.add("x conhece Beta.", other, "x", datetime(2026, 4, 2, tzinfo=UTC))
        assert s.stats(g)["entities"] == 3 and s.stats(g)["facts"] == 2  # o outro grupo não mexeu neste
        assert evil in [e["name"] for e in (await s.search("Beta", [other], 5, True))["entities"]]
        assert (await s.search("ACME", [other], 5, True))["facts"] == [] or all(
            f["group"] == other for f in (await s.search("ACME", [other], 5, True))["facts"])
        assert len(s.recent(g, 10)) == 2
    asyncio.run(run())
    s.clear(g)
    assert s.stats(g) == {"entities": 0, "facts": 0, "graph": None} and s.stats(other)["facts"] == 1
    s.clear(other)
    s.pool.close()
