"""Hub HangarLLM: ligar com a chave de gestão, a conexão `hangarllm` com os modelos do gateway, a chave virtual por agente
e ambiente no deploy (nunca a de gestão nem a da central), renovação, gasto real, revogação e o modo isolado intacto."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import crypto
from app.db import SessionLocal
from app.models import HubKey
from app.services import hangarllm, llm_models

from .conftest import ADMIN

URL = "http://hangarllm.test:4000"
ADMIN_KEY = "hgr_admin_master"
MODELS = [
    {"model_name": "deepseek-flash", "model_info": {"mode": "chat", "input_cost_per_token": 1e-7,
                                                     "output_cost_per_token": 4e-7, "max_input_tokens": 128000,
                                                     "supports_function_calling": True}},
    {"model_name": "deepseek-flash", "model_info": {"mode": "chat"}},  # outro deployment do mesmo grupo
    {"model_name": "gpt-mini", "model_info": {"mode": "chat", "input_cost_per_token": 1.5e-7}},
    {"model_name": "dec-openai", "model_info": {"mode": "decisions"}},
    {"model_name": "embed-small", "model_info": {"mode": "embedding"}},
]


class FakeHub:
    """O HangarLLM falso: confere a chave de gestão, cria/atualiza/apaga chaves e devolve o gasto de cada uma."""

    def __init__(self):
        self.keys: dict[str, dict] = {}  # token -> {key, alias, models, expires, spend}
        self.calls: list[tuple[str, str, dict]] = []
        self.n = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, auth = req.url.path, req.headers.get("authorization", "")
        body = json.loads(req.content) if req.content else {}
        self.calls.append((req.method, path, body))
        if path == "/health/readiness":
            return httpx.Response(200, json={"status": "healthy", "db": "connected"})
        if auth != f"Bearer {ADMIN_KEY}":
            return httpx.Response(401, json={"error": "Authentication Error"})
        if path == "/model/info":
            return httpx.Response(200, json={"data": MODELS})
        if path == "/key/list":
            rows = [{"key_alias": k["alias"], "spend": k["spend"], "token": t} for t, k in self.keys.items()]
            return httpx.Response(200, json={"keys": rows, "total_count": len(rows), "current_page": 1, "total_pages": 1})
        if path == "/key/generate":
            assert body["duration"] and body["max_budget"] and body["models"]  # a política de chaves do HangarLLM
            self.n += 1
            token, key = f"tok{self.n}", f"hgr_virtual_{self.n}"
            exp = (datetime.now(UTC) + timedelta(days=30)).isoformat()
            self.keys[token] = {"key": key, "alias": body["key_alias"], "models": body["models"], "expires": exp,
                                "spend": 0.0, "metadata": body.get("metadata")}
            return httpx.Response(200, json={"key": key, "token": token, "expires": exp, "key_alias": body["key_alias"]})
        if path == "/key/update":
            k = self.keys[body["key"]]
            k["models"] = body.get("models", k["models"])
            if body.get("duration"):
                k["expires"] = (datetime.now(UTC) + timedelta(days=30)).isoformat()
            return httpx.Response(200, json={"expires": k["expires"]})
        if path == "/key/delete":
            for t in body["keys"]:
                self.keys.pop(t, None)
            return httpx.Response(200, json={"deleted_keys": body["keys"]})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture()
def hub(monkeypatch):
    fake = FakeHub()
    monkeypatch.setattr(hangarllm, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))

    def get(url, headers, params=None):  # a lista de modelos da conexão sai do mesmo HangarLLM falso
        r = fake.handler(httpx.Request("GET", url, headers=headers))
        if r.status_code >= 400:
            raise llm_models.ModelsError(f"HTTP {r.status_code} em {url}")
        return r.json()
    monkeypatch.setattr(llm_models, "_get", get)
    yield fake
    with SessionLocal() as db:  # um hub por empresa: cada teste sai com ele desligado
        if hangarllm.link(db) is not None:
            for k in db.scalars(select(HubKey)):
                db.delete(k)
            db.delete(hangarllm.link(db))
            db.commit()
        from app.models import LlmConnection, LlmModel
        for c in db.scalars(select(LlmConnection).where(LlmConnection.provider == "hangarllm")).all():
            db.query(LlmModel).filter(LlmModel.connection_id == c.id).delete()
            db.delete(c)
        db.commit()


def _connect(client, **over):
    return client.put("/api/hangarllm", headers=ADMIN, json={"url": URL, "admin_key": ADMIN_KEY, "budget_usd": 5,
                                                            "budget_period": "30d", **over})


def _agent(client, uniq, model=None):
    slug = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Hub"), "objective": "o", "final_output": "f"}).json()["slug"]
    llm = {"connection": "hangarllm", **({"model": model} if model else {})}
    assert client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"llm": llm}).status_code == 200
    return slug


def test_connecting_checks_the_key_and_brings_the_gateway_models(client, hub):
    assert client.get("/api/hangarllm", headers=ADMIN).json()["connected"] is False
    r = _connect(client, admin_key="errada")
    assert r.status_code == 400 and "chave inválida" in r.json()["detail"]
    r = _connect(client)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["connected"] and s["connection"] == "hangarllm" and s["sync"]["ok"]
    assert s["models"] == {"text": 2, "other": 1, "embedding": 1} and s["default_model"] == "deepseek-flash"
    assert s["budget_usd"] == 5
    # a conexão guarda a chave da central (virtual, com os modelos do hub), nunca a de gestão
    with SessionLocal() as db:
        conn = hangarllm.connection(db)
        assert conn.provider == "hangarllm" and conn.base_url == f"{URL}/v1"
        central = crypto.decrypt(conn.api_key)
        assert central.startswith("hgr_virtual_") and central != ADMIN_KEY
        m = db.scalar(select(llm_models.LlmModel).where(llm_models.LlmModel.connection_id == conn.id,
                                                        llm_models.LlmModel.model_id == "deepseek-flash"))
        assert (m.price_in_per_mtok, m.price_out_per_mtok, m.price_source) == (0.1, 0.4, "provider")
    gen = [b for meth, p, b in hub.calls if p == "/key/generate"]
    assert gen[0]["key_alias"].endswith("/central") and set(gen[0]["models"]) == {"deepseek-flash", "gpt-mini",
                                                                                  "dec-openai", "embed-small"}
    # a tela não devolve chave nenhuma
    assert ADMIN_KEY not in json.dumps(s) and "hgr_virtual" not in json.dumps(s)
    # o hub não se cria nem se remove pelo cadastro comum de provedores
    r = client.post("/api/catalog/llm", headers=ADMIN, json={"name": "x", "provider": "hangarllm", "base_url": URL,
                                                               "api_key": "k", "model_name": "m"})
    assert r.status_code == 400 and "Hub HangarLLM" in r.json()["detail"]
    assert client.delete("/api/catalog/llm/hangarllm", headers=ADMIN).status_code == 400
    # reenviar sem a chave mantém a atual
    assert _connect(client, admin_key="", budget_usd=7).json()["budget_usd"] == 7


def test_each_agent_gets_its_own_key_only_with_its_models(client, hub, uniq, monkeypatch):
    from app import deploy
    assert _connect(client).status_code == 200
    seen = {}
    real = deploy.run_agent

    def run(slug, env, spec, llm_conf):
        seen[slug] = llm_conf
        return real(slug, env, spec, llm_conf)
    monkeypatch.setattr(deploy, "run_agent", run)
    a, b = _agent(client, uniq), _agent(client, uniq, model="gpt-mini")
    for slug in (a, b):
        assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200
    ka, kb = seen[a]["api_key"], seen[b]["api_key"]
    assert seen[a]["gateway"] == "hangarllm" and ka != kb and ADMIN_KEY not in (ka, kb)
    with SessionLocal() as db:
        central = crypto.decrypt(hangarllm.connection(db).api_key)
    assert central not in (ka, kb)
    by_key = {k["key"]: k for k in hub.keys.values()}
    assert by_key[ka]["models"] == ["deepseek-flash"] and by_key[kb]["models"] == ["gpt-mini"]
    assert by_key[ka]["alias"].endswith(f"/{a}/stage")
    assert {"agent": a, "env": "stage"}.items() <= by_key[ka]["metadata"]["agent_hangar"].items()
    # redeploy reaproveita a chave; trocar o modelo só acerta os modelos da mesma chave
    n = len([c for c in hub.calls if c[1] == "/key/generate"])
    client.patch(f"/api/agents/{a}", headers=ADMIN, json={"llm": {"model": "gpt-mini"}})
    assert client.post(f"/api/agents/{a}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200
    assert seen[a]["api_key"] == ka and len([c for c in hub.calls if c[1] == "/key/generate"]) == n
    assert by_key[ka]["models"] == ["gpt-mini"]
    # a tela lista as chaves com o agente, sem o valor
    s = client.get("/api/hangarllm", headers=ADMIN).json()
    rows = {(k["agent"], k["env"]) for k in s["keys"] if not k["central"]}
    assert {(a, "stage"), (b, "stage")} <= rows


def test_renewal_spend_and_revocation(client, hub, uniq):
    assert _connect(client).status_code == 200
    slug = _agent(client, uniq)
    assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200
    with SessionLocal() as db:
        k = db.scalar(select(HubKey).where(HubKey.alias.endswith(f"/{slug}/stage")))
        k.expires_at = datetime.now(UTC) + timedelta(days=2)  # perto de vencer
        db.commit()
        token = k.token
    hub.keys[token]["spend"] = 0.0123
    s = client.post("/api/hangarllm/refresh", headers=ADMIN).json()
    assert s["renewed"] == 1 and s["status"] == "ok"
    row = next(x for x in s["keys"] if x["agent"] == slug)
    assert row["spend_usd"] == 0.0123 and s["spend_usd"] >= 0.0123
    exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    assert (exp if exp.tzinfo else exp.replace(tzinfo=UTC)) > datetime.now(UTC) + timedelta(days=20)
    # excluir o agente revoga a chave no HangarLLM
    assert client.delete(f"/api/agents/{slug}", headers=ADMIN).status_code == 200
    assert token not in hub.keys
    with SessionLocal() as db:
        assert db.scalar(select(HubKey).where(HubKey.token == token)) is None


def test_hub_offline_is_reported_and_disconnecting_needs_no_agent_on_it(client, hub, uniq, monkeypatch):
    assert _connect(client).status_code == 200
    slug = _agent(client, uniq)
    assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200

    def down(req):
        raise httpx.ConnectError("recusado")
    monkeypatch.setattr(hangarllm, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(down)))
    s = client.post("/api/hangarllm/refresh", headers=ADMIN).json()
    assert s["status"] == "error" and "não consegui falar" in s["error"]
    monkeypatch.setattr(hangarllm, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(hub.handler)))
    r = client.delete("/api/hangarllm", headers=ADMIN)
    assert r.status_code == 400 and slug in r.json()["detail"]  # um agente ainda usa a conexão
    from app import services as svc
    from app.models import Agent
    with SessionLocal() as db:  # este e os agentes de outros testes que ficaram na conexão saem dela
        users = [a.slug for a in db.scalars(select(Agent)) if svc.uses_connection(svc.spec_of(a), "hangarllm")]
    for s_ in users:
        client.patch(f"/api/agents/{s_}", headers=ADMIN, json={"llm": None})
    tokens = set(hub.keys)
    r = client.delete("/api/hangarllm", headers=ADMIN)
    assert r.status_code == 200 and r.json()["revoked"] == len(tokens) and hub.keys == {}
    assert client.get("/api/hangarllm", headers=ADMIN).json()["connected"] is False


def test_the_isolated_path_is_untouched(client, hub, uniq):
    r = client.post("/api/catalog/llm", headers=ADMIN, json={"name": uniq("direto"), "provider": "custom",
                                                               "base_url": "http://hangarllm:4000/v1", "api_key": "k",
                                                               "model_name": "m"})
    assert r.status_code == 200 and r.json()["provider"] == "custom"  # o endereço não vira hub sozinho
    with SessionLocal() as db:
        out = hangarllm.status(db)
        assert out["connected"] is False and out["isolated"]["llm_connections"] >= 1


def test_hangar_setup_connects_the_hub(client, hub, monkeypatch):
    """`hangar setup` com o HangarLLM: só endereço e chave de gestão (o modelo padrão vem da lista do hub)."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cli"))
    from hangar_cli import setup as st
    with pytest.raises(st.SetupError, match="llm.api_key"):
        st.validate({"llm": {"provider": "hangarllm", "base_url": URL}})
    a = st.validate({"llm": {"provider": "hangarllm", "base_url": URL, "api_key": ADMIN_KEY},
                     "admin": {"username": "admin"}, "code_policy": "any", "clients": []})
    assert a["llm"]["name"] == "hangarllm" and a["llm"]["model"] == ""
    monkeypatch.setattr(st.httpx, "request", lambda method, url, **kw: client.request(
        method, url.replace("http://testserver", ""), headers=kw.get("headers"), json=kw.get("json")))
    st.configure(st.Api("http://testserver", "test-admin-token"), a, "http://testserver")
    s = client.get("/api/hangarllm", headers=ADMIN).json()
    assert s["connected"] and s["models_total"] == 4
    conns = {c["name"]: c for c in client.get("/api/catalog", headers=ADMIN).json()["llm_connections"]}
    assert conns["hangarllm"]["allow_code"] is True and conns["hangarllm"]["provider"] == "hangarllm"
