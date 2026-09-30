"""Governança dos agentes de código: política da empresa (conexões aprovadas para código), bloqueio no gateway, no
teste de conexão e na avaliação de código; máscara de segredos no runtime; template "Agente de código"."""
import pytest

from app import services as svc
from app.db import SessionLocal
from app.routers.gateway import _sends_client_tools

from .conftest import ADMIN
from .test_access import org_setup  # noqa: F401  (fixture)
from .test_runtime import rt  # noqa: F401  (fixture)


@pytest.fixture()
def approved_only(client):
    assert client.patch("/api/org", headers=ADMIN, json={"code_policy": "approved"}).json()["code_policy"] == "approved"
    yield
    client.patch("/api/org", headers=ADMIN, json={"code_policy": "any"})


def _conn(uniq):
    name = uniq("llm")
    with SessionLocal() as db:
        svc.upsert_llm_connection(db, name, "https://llm.test/v1", "m-1", api_key="k")
    return name


def test_policy_and_approval_endpoints(client, uniq, org_setup):  # noqa: F811
    assert client.patch("/api/org", headers=ADMIN, json={"code_policy": "talvez"}).status_code == 400
    assert client.patch("/api/org", headers=org_setup["h"]["maint"], json={"code_policy": "approved"}).status_code == 403
    name = _conn(uniq)
    assert client.patch(f"/api/catalog/llm/{name}/code", headers=org_setup["h"]["maint"], json={"allow_code": True}).status_code == 403
    r = client.patch(f"/api/catalog/llm/{name}/code", headers=ADMIN, json={"allow_code": True})
    assert r.status_code == 200 and r.json()["allow_code"] is True
    assert any(c["name"] == name and c["allow_code"] for c in client.get("/api/catalog", headers=ADMIN).json()["llm_connections"])


def test_code_allowed_rules(client, uniq, approved_only):
    ok_conn, other = _conn(uniq), _conn(uniq)
    client.patch(f"/api/catalog/llm/{ok_conn}/code", headers=ADMIN, json={"allow_code": True})
    with SessionLocal() as db:
        assert svc.code_allowed(db, {"llm": {"connection": ok_conn}}, "prod") == (True, "")
        allowed, msg = svc.code_allowed(db, {"llm": {"connection": other}}, "prod")
        assert not allowed and other in msg and "aprovada" in msg
        assert svc.code_allowed(db, {"llm": {}}, "prod")[0]  # mock: nada sai para um LLM
        # override por ambiente: o que vale é a conexão efetiva do ambiente
        spec = {"llm": {"connection": ok_conn, "stage": {"connection": other}}}
        assert svc.code_allowed(db, spec, "prod")[0] and not svc.code_allowed(db, spec, "stage")[0]


def test_policy_any_allows_everything(client, uniq):
    with SessionLocal() as db:
        assert svc.code_allowed(db, {"llm": {"connection": _conn(uniq)}}, "prod") == (True, "")


def test_gateway_blocks_coding_mode_only(client, uniq, approved_only):
    name = _conn(uniq)
    slug = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Coder"), "objective": "o", "final_output": "f"}).json()["slug"]
    client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"llm": {"connection": name}})
    assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200
    body = {"model": slug, "messages": [{"role": "user", "content": "oi"}]}
    r = client.post(f"/gw-stage/{slug}/v1/chat/completions", headers=ADMIN,
                    json={**body, "tools": [{"type": "function", "function": {"name": "read_file"}}]})
    assert r.status_code == 403 and r.json()["error"]["type"] == "code_policy"
    # sem ferramentas do cliente (chat comum) a política não se aplica: segue para o agente
    assert client.post(f"/gw-stage/{slug}/v1/chat/completions", headers=ADMIN, json=body).status_code != 403
    # o teste de conexão explica o motivo
    t = client.post(f"/api/agents/{slug}/connections/test", headers=ADMIN, json={"env": "stage"}).json()
    assert not t["ok"] and t["steps"][0]["name"] == "política de código"


def test_code_eval_respects_policy(client, uniq, approved_only, monkeypatch):
    from app.services import testing
    name = _conn(uniq)
    monkeypatch.setattr(testing, "is_mock", lambda spec, env="stage": False)
    with SessionLocal() as db:
        ok, detail = testing._code_case(db, None, {"llm": {"connection": name}}, {"workspace": {}})
    assert not ok and "aprovada para receber código" in detail


def test_sends_client_tools():
    assert _sends_client_tools(b'{"tools": [{"type": "function"}]}')
    assert not _sends_client_tools(b'{"tools": []}') and not _sends_client_tools(b'{"messages": []}')
    assert not _sends_client_tools(b'{"tools": ')  # corpo inválido: o agente responde o erro


# ------------------------------------------------------------------ runtime: máscara de segredos
ENV_FILE = ("DATABASE_URL=postgresql://app:S3nh4F0rte@db:5432/app\nOPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456\n"
            "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\npassword = \"hunter2hunter2\"\ntoken = get_token()\nDEBUG=true\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----\n")


def test_redact_masks_values_and_keeps_code(rt):  # noqa: F811
    out, n = rt.redact(ENV_FILE)
    assert n == 5
    for secret in ("S3nh4F0rte", "sk-proj-", "AKIAABCD", "hunter2", "MIIEow"):
        assert secret not in out
    assert "postgresql://app:" in out and "OPENAI_API_KEY=" in out  # nomes e estrutura continuam
    assert "token = get_token()" in out and "DEBUG=true" in out      # código comum não é tocado


def test_redaction_only_in_coding_mode(rt, monkeypatch):  # noqa: F811
    import asyncio

    from .test_runtime import _fake_llm
    seen = _fake_llm(rt, monkeypatch, [{"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}}])

    async def tools():
        return []
    monkeypatch.setattr(rt, "get_tools", tools)
    rt.MODE.set("full")
    history = [{"role": "user", "content": "leia o .env"},
               {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                                                                       "function": {"name": "read_file", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c1", "content": ENV_FILE}]
    read_file = {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    asyncio.run(rt.chat_full(history, [read_file]))
    sent = seen[-1]["messages"][-1]["content"]
    assert "S3nh4F0rte" not in sent and "segredo(s) mascarado(s)" in sent
    monkeypatch.setattr(rt, "REDACT", False)
    asyncio.run(rt.chat_full(history, [read_file]))
    assert "S3nh4F0rte" in seen[-1]["messages"][-1]["content"]


# ------------------------------------------------------------------ template
def test_code_assistant_template(client, uniq):
    t = next(x for x in client.get("/api/templates", headers=ADMIN).json() if x["id"] == "code-assistant")
    assert "coding" in t["tags"]
    tpl = svc.get_template("code-assistant")
    from app.spec import validate
    agent = tpl["document"]["agents"][0]
    v = validate(agent["spec"])
    code_cases = [c for c in v["tests"] if c.get("workspace")]
    assert len(code_cases) == 2 and all(c["workspace"]["protected"] for c in code_cases)
    assert v["llm"]["max_steps"] == 30
