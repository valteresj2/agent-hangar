"""Hub HangarLLM, etapa 2: os servidores MCP do gateway viram conectores `hub:<alias>` que o agente chama pela ponte com a
chave dele (só os servidores da spec dele, com etiquetas), as skills vão nos dois sentidos (as do Skill Hub chegam aqui
somente leitura; as da empresa vão para lá) e, sem endereço, a central acha o HangarLLM no Docker e liga sozinha."""
import contextlib
import io
import json
import socket
import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import auth, crypto, deploy
from app.db import SessionLocal
from app.models import HubKey, McpServer, Skill
from app.services import hangarllm, llm_models

from .conftest import ADMIN

ADMIN_KEY = "hgr_admin_master"
MODELS = [{"model_name": "deepseek-flash", "model_info": {"mode": "chat", "input_cost_per_token": 1e-7}}]
SEEN: list[dict] = []  # os headers que o "gateway de MCP" recebeu


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def gateway():
    """O gateway de MCP do HangarLLM: /labmcp/mcp com as ferramentas como <alias>-<ferramenta> e a chave conferida."""
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount

    srv = FastMCP("labmcp", stateless_http=True, json_response=True, streamable_http_path="/mcp",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    @srv.tool(name="labmcp-add", description="Soma dois números.")
    def add(a: int, b: int) -> int:
        return a + b

    class Keys(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            SEEN.append({k.lower(): v for k, v in request.headers.items()})
            if not request.headers.get("x-hangarllm-api-key", "").startswith("hgr_virtual_"):
                return PlainTextResponse("no key", 401)
            return await call_next(request)
    inner = srv.streamable_http_app()
    inner.add_middleware(Keys)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with srv.session_manager.run():
            yield
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(Starlette(routes=[Mount("/labmcp", app=inner)], lifespan=lifespan),
                                           host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def _skill_zip(name: str, description: str, body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")
    return buf.getvalue()


class FakeHub:
    """A API de gestão do HangarLLM: chaves (com a permissão de MCP), servidores MCP e o Skill Hub."""

    def __init__(self):
        self.keys: dict[str, dict] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.servers = [{"server_id": "s1", "server_name": "labmcp", "alias": "labmcp", "description": "Laboratório",
                         "transport": "http", "approval_status": "active"}]
        self.skills: dict[str, dict] = {}
        self.upload_limit = 1000
        self.n = 0

    def add_skill(self, name, description="vem do hub", body="Corpo do hub", version="1.0.0", keywords=None):
        self.skills[name] = {"name": name, "description": description, "version": version, "visibility": "public",
                             "keywords": keywords or [], "updated_at": datetime.now(UTC).isoformat(),
                             "zip": _skill_zip(name, description, body)}

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, auth_h = req.url.path, req.headers.get("authorization", "")
        multipart = req.headers.get("content-type", "").startswith("multipart/")
        body = {} if multipart or not req.content else json.loads(req.content)
        self.calls.append((req.method, path, body))
        if path == "/health/readiness":
            return httpx.Response(200, json={"status": "healthy"})
        if auth_h != f"Bearer {ADMIN_KEY}":
            return httpx.Response(401, json={"error": "Authentication Error"})
        if path == "/model/info":
            return httpx.Response(200, json={"data": MODELS})
        if path == "/key/list":
            rows = [{"key_alias": k["alias"], "spend": 0, "token": t} for t, k in self.keys.items()]
            return httpx.Response(200, json={"keys": rows, "total_pages": 1})
        if path == "/key/generate":
            assert body["duration"] and body["max_budget"] and body["models"] and body["auto_rotate"] is False
            self.n += 1
            token, key = f"tok{self.n}", f"hgr_virtual_{self.n}"
            exp = (datetime.now(UTC) + timedelta(days=30)).isoformat()
            self.keys[token] = {"key": key, "alias": body["key_alias"], "models": body["models"],
                                "mcp": body["object_permission"]["mcp_servers"], "expires": exp}
            return httpx.Response(200, json={"key": key, "token": token, "expires": exp})
        if path == "/key/update":
            k = self.keys[body["key"]]
            k["models"] = body.get("models", k["models"])
            k["mcp"] = (body.get("object_permission") or {}).get("mcp_servers", k["mcp"])
            return httpx.Response(200, json={"expires": k["expires"]})
        if path == "/key/delete":
            for t in body["keys"]:
                self.keys.pop(t, None)
            return httpx.Response(200, json={"deleted_keys": body["keys"]})
        if path == "/v1/mcp/server":
            return httpx.Response(200, json=self.servers)
        if path == "/skill-hub/skills" and req.method == "GET":
            rows = [{k: v for k, v in s.items() if k != "zip"} for s in self.skills.values()]
            return httpx.Response(200, json={"skills": rows, "count": len(rows), "next_offset": None})
        if path.startswith("/skill-hub/skills/") and path.endswith("/archive"):
            return httpx.Response(200, content=self.skills[path.split("/")[3]]["zip"])
        if path.endswith("/upload"):
            if self.upload_limit <= 0:
                return httpx.Response(429, json={"detail": "Skills Hub allows 10 uploads or imports per minute per user"})
            self.upload_limit -= 1
            data = req.content
            zbytes = data[data.index(b"PK\x03\x04"):data.rindex(b"\r\n--")]
            md = zipfile.ZipFile(io.BytesIO(zbytes)).read("SKILL.md").decode()
            assert md.startswith("---")  # SKILL.md na raiz do zip
            name = md.split("name: ", 1)[1].split("\n", 1)[0].strip()
            version = data.split(b'name="version"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode()
            if req.method == "POST" and name in self.skills:
                return httpx.Response(409, json={"detail": "exists"})
            cur = self.skills.get(name, {})
            self.skills[name] = {**cur, "name": name, "description": "", "version": version, "visibility": "public",
                                 "keywords": cur.get("keywords", []), "updated_at": datetime.now(UTC).isoformat(),
                                 "zip": zbytes, "md": md}
            return httpx.Response(201, json={"name": name, "version": version})
        if path.startswith("/skill-hub/skills/") and req.method == "PUT":
            self.skills[path.split("/")[3]].update(body)
            return httpx.Response(200, json={"ok": True})
        if path.startswith("/skill-hub/skills/") and req.method == "DELETE":
            self.skills.pop(path.split("/")[3], None)
            return httpx.Response(204)
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture()
def hub(monkeypatch):
    fake = FakeHub()
    monkeypatch.setattr(hangarllm, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))

    def get(url, headers, params=None):
        r = fake.handler(httpx.Request("GET", url, headers=headers))
        if r.status_code >= 400:
            raise llm_models.ModelsError(f"HTTP {r.status_code} em {url}")
        return r.json()
    monkeypatch.setattr(llm_models, "_get", get)
    yield fake
    with SessionLocal() as db:  # cada teste sai com o hub desligado e sem as peças que vieram dele
        for m in db.scalars(select(McpServer).where(McpServer.source == "hub")).all():
            db.delete(m)
        for s in db.scalars(select(Skill)).all():
            if s.source == "hub":
                db.delete(s)
            else:
                s.hub_ref = ""
        for k in db.scalars(select(HubKey)).all():
            db.delete(k)
        if hangarllm.link(db) is not None:
            db.delete(hangarllm.link(db))
        from app.models import LlmConnection, LlmModel
        for c in db.scalars(select(LlmConnection).where(LlmConnection.provider == "hangarllm")).all():
            db.query(LlmModel).filter(LlmModel.connection_id == c.id).delete()
            db.delete(c)
        db.commit()


def _connect(client, url, **over):
    r = client.put("/api/hangarllm", headers=ADMIN, json={"url": url, "admin_key": ADMIN_KEY, "budget_usd": 5, **over})
    assert r.status_code == 200, r.text
    return r.json()


def _agent(client, uniq, **spec):
    slug = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Hub"), "objective": "o", "final_output": "f"}).json()["slug"]
    assert client.patch(f"/api/agents/{slug}", headers=ADMIN, json=spec).status_code == 200
    return slug


def _rpc(client, slug, method, params=None, **headers):
    h = {"X-Agent-Slug": slug, "Authorization": f"Bearer {auth.agent_token(slug)}",
         "Accept": "application/json, text/event-stream", **headers}
    return client.post("/internal/mcp-proxy/hub:labmcp", headers=h,
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_hub_mcp_servers_become_connectors_the_agent_calls_with_its_own_key(client, hub, gateway, uniq):
    s = _connect(client, gateway)
    assert s["hub_sync"]["mcps"]["added"] == ["hub:labmcp"]
    m = next(x for x in s["mcps"] if x["name"] == "hub:labmcp")
    assert m["status"] == "ok" and m["tools"] == 1 and m["used_by"] == []
    central = next(k for k in hub.keys.values() if k["alias"].endswith("/central"))
    assert central["mcp"] == ["labmcp"]  # a central confere os servidores com a chave dela
    with SessionLocal() as db:
        row = db.scalar(select(McpServer).where(McpServer.name == "hub:labmcp"))
        assert row.source == "hub" and row.auth == "hub" and row.tool_prefix == "labmcp-"
        assert row.upstream_url == f"{gateway}/labmcp/mcp" and row.url.endswith("/internal/mcp-proxy/hub:labmcp")
    # um agente com LLM de fora do hub e só o MCP do hub: a chave dele não chama modelo nenhum
    slug = _agent(client, uniq, mcps=["hub:labmcp"])
    SEEN.clear()
    r = _rpc(client, slug, "tools/list", **{"X-Agent-Env": "prod", "X-Hangar-Task": "42"})
    assert r.status_code == 200, r.text
    assert [t["name"] for t in r.json()["result"]["tools"]] == ["labmcp-add"]
    mine = next(k for k in hub.keys.values() if k["alias"].endswith(f"/{slug}/prod"))
    assert mine["models"] == ["no-default-models"] and mine["mcp"] == ["labmcp"]
    got = SEEN[-1]
    assert got["x-hangarllm-api-key"] == mine["key"] and got["x-hangarllm-api-key"] != central["key"]
    assert ADMIN_KEY not in json.dumps(SEEN)
    assert got["x-hangarllm-tags"] == f"agent-hangar,agent:{slug},env:prod,task:42"
    assert got["x-hangarllm-session-id"] == f"{slug}-task-42"
    r = _rpc(client, slug, "tools/call", {"name": "labmcp-add", "arguments": {"a": 2, "b": 3}}, **{"X-Agent-Env": "prod"})
    assert r.json()["result"]["content"][0]["text"] == "5"
    assert client.get("/api/hangarllm", headers=ADMIN).json()["keys"][-1]["mcps"] == ["labmcp"]
    # o conector do hub não se remove por aqui; se sai do hub e ainda está em uso, fica marcado
    assert client.delete("/api/connectors/hub:labmcp", headers=ADMIN).status_code == 400
    hub.servers = []
    s = client.post("/api/hangarllm/refresh", headers=ADMIN).json()
    assert s["hub_sync"]["mcps"]["orphaned"] == ["hub:labmcp"]
    assert "removido do HangarLLM" in next(x for x in s["mcps"] if x["name"] == "hub:labmcp")["status_detail"]
    assert client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"mcps": []}).status_code == 200
    s = client.post("/api/hangarllm/refresh", headers=ADMIN).json()
    assert s["hub_sync"]["mcps"]["removed"] == ["hub:labmcp"] and s["mcps"] == []
    # excluir o agente revoga a chave dele no hub
    client.delete(f"/api/agents/{slug}", headers=ADMIN)
    assert not any(k["alias"].endswith(f"/{slug}/prod") for k in hub.keys.values())


def test_an_agent_on_the_hub_llm_gets_one_key_with_its_models_and_its_hub_servers(client, hub, gateway, uniq):
    _connect(client, gateway)
    slug = _agent(client, uniq, llm={"connection": "hangarllm"}, mcps=["hub:labmcp"])
    assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200
    with SessionLocal() as db:
        k = db.scalar(select(HubKey).where(HubKey.alias.like(f"%/{slug}/stage")))
        assert k.models == ["deepseek-flash"] and k.mcps == ["labmcp"]
        value = crypto.decrypt(k.key)
    gen = [b for meth, p, b in hub.calls if p == "/key/generate" and b["key_alias"].endswith(f"/{slug}/stage")]
    assert len(gen) == 1 and gen[0]["object_permission"] == {"mcp_servers": ["labmcp"]}
    SEEN.clear()
    assert _rpc(client, slug, "tools/list", **{"X-Agent-Env": "stage"}).status_code == 200
    assert SEEN[-1]["x-hangarllm-api-key"] == value  # a mesma chave do LLM, sem chave nova
    assert len([1 for meth, p, b in hub.calls if p == "/key/generate" and b["key_alias"].endswith(f"/{slug}/stage")]) == 1
    client.delete(f"/api/agents/{slug}", headers=ADMIN)


def test_skills_come_from_the_hub_read_only_and_company_skills_go_there(client, hub, gateway, uniq):
    hub.add_skill("hub-revisao", "Revisa textos", "Aponte erros de ortografia.")
    local = uniq("tom-local")
    assert client.post("/api/catalog/skills", headers=ADMIN, json={"name": local, "description": "Tom da empresa",
                                                                   "content": "Fale com calma."}).status_code == 200
    clash = uniq("mesmo-nome")
    client.post("/api/catalog/skills", headers=ADMIN, json={"name": clash, "description": "daqui", "content": "local"})
    hub.add_skill(clash, "de lá", "do hub")
    s = _connect(client, gateway)
    res = s["hub_sync"]["skills"]
    assert "hub-revisao" in res["pulled"] and local in res["pushed"] and clash in res["conflicts"]
    with SessionLocal() as db:
        got = db.scalar(select(Skill).where(Skill.name == "hub-revisao"))
        assert got.source == "hub" and "Aponte erros" in got.content and got.description == "Revisa textos"
        assert db.scalar(select(Skill).where(Skill.name == clash)).content == "local"  # não sobrescreve
    assert hub.skills[clash]["description"] == "de lá"  # nem lá
    # a do hub é somente leitura aqui
    sk = next(x for x in client.get("/api/skills", headers=ADMIN).json() if x["name"] == "hub-revisao")
    assert sk["source"] == "hub" and sk["can_edit"] is False
    assert client.put("/api/skills/hub-revisao", headers=ADMIN, json={"content": "mudei"}).status_code == 403
    # a da empresa chegou ao Skill Hub com a palavra-chave da empresa e o SKILL.md na raiz
    pushed = hub.skills[local]
    assert "agent-hangar" in pushed["keywords"] and "Fale com calma." in pushed["md"] and pushed["version"] == "1.0.0"
    # versão nova lá: chega aqui; versão nova aqui: vai para lá (substitui, não duplica)
    hub.add_skill("hub-revisao", "Revisa textos", "Aponte erros e sugira a correção.", version="1.1.0")
    client.post("/api/catalog/skills", headers=ADMIN, json={"name": local, "description": "Tom da empresa",
                                                           "content": "Fale com calma e cordialidade."})
    res = client.post("/api/hangarllm/refresh", headers=ADMIN).json()["hub_sync"]["skills"]
    assert "hub-revisao" in res["pulled"] and local in res["pushed"]
    assert hub.skills[local]["version"] == "2.0.0" and "cordialidade" in hub.skills[local]["md"]
    assert ("PUT", f"/skill-hub/skills/{local}/upload") in [(m, p) for m, p, b in hub.calls]
    with SessionLocal() as db:
        assert "sugira a correção" in db.scalar(select(Skill).where(Skill.name == "hub-revisao")).content
    # nada mudou: nada vai nem volta
    res = client.post("/api/hangarllm/refresh", headers=ADMIN).json()["hub_sync"]["skills"]
    assert res["pulled"] == [] and res["pushed"] == []
    # tirada do hub (sem uso aqui): sai daqui também
    hub.skills.pop("hub-revisao")
    res = client.post("/api/hangarllm/refresh", headers=ADMIN).json()["hub_sync"]["skills"]
    assert "hub-revisao" in res["removed"]
    # publicação desligada: as da empresa saem do Skill Hub
    s = client.put("/api/hangarllm", headers=ADMIN, json={"url": gateway, "share_skills": False}).json()
    assert s["share_skills"] is False and local in s["hub_sync"]["skills"]["unpublished"] and local not in hub.skills


def test_the_upload_limit_stops_the_round_and_the_next_one_continues(client, hub, gateway, uniq):
    for i in range(3):
        client.post("/api/catalog/skills", headers=ADMIN, json={"name": uniq(f"lim{i}"), "description": "d", "content": "c"})
    hub.upload_limit = 1
    res = _connect(client, gateway)["hub_sync"]["skills"]
    assert len(res["pushed"]) == 1 and any("429" in e for e in res["errors"])
    hub.upload_limit = 1000
    res = client.post("/api/hangarllm/refresh", headers=ADMIN).json()["hub_sync"]["skills"]
    assert res["pushed"] and not res["errors"]


def test_disconnecting_cleans_the_hub_pieces_and_keeps_pulled_skills_as_company_skills(client, hub, gateway, uniq):
    hub.add_skill("hub-guia", "Guia", "Siga o guia.")
    local = uniq("publicada")
    client.post("/api/catalog/skills", headers=ADMIN, json={"name": local, "description": "d", "content": "c"})
    _connect(client, gateway)
    assert local in hub.skills
    slug = _agent(client, uniq, mcps=["hub:labmcp"])
    r = client.delete("/api/hangarllm", headers=ADMIN)
    assert r.status_code == 400 and slug in r.json()["detail"]  # conector do hub em uso
    client.delete(f"/api/agents/{slug}", headers=ADMIN)
    assert client.delete("/api/hangarllm", headers=ADMIN).status_code == 200
    assert local not in hub.skills and hub.keys == {}
    with SessionLocal() as db:
        assert db.scalar(select(McpServer).where(McpServer.source == "hub")) is None
        kept = db.scalar(select(Skill).where(Skill.name == "hub-guia"))
        assert kept is not None and kept.source == "" and kept.hub_ref == ""


def test_plug_and_play_finds_the_local_hangarllm_in_docker(client, hub, monkeypatch):
    joined = []

    class Net:
        def __init__(self, name):
            self.name = name

        def connect(self, c, aliases):
            joined.append((self.name, aliases))

    class Ctr:
        name = "hangarllm-hangarllm-1"
        attrs = {"Config": {"Image": "hangarllm:latest", "ExposedPorts": {"4000/tcp": {}}},
                 "NetworkSettings": {"Networks": {"hangarllm_default": {}}}}

    class Other:
        name = "hangarllm-db-1"
        attrs = {"Config": {"Image": "postgres:16", "ExposedPorts": {"5432/tcp": {}}}, "NetworkSettings": {"Networks": {}}}

    class Docker:
        containers = type("C", (), {"list": staticmethod(lambda: [Other(), Ctr()]), "get": staticmethod(lambda n: Ctr())})
        networks = type("N", (), {"get": staticmethod(Net)})

    monkeypatch.setattr(deploy, "client", lambda: Docker())
    s = client.get("/api/hangarllm", headers=ADMIN).json()
    assert s["connected"] is False and [f["container"] for f in s["found"]] == ["hangarllm-hangarllm-1"]
    r = client.put("/api/hangarllm", headers=ADMIN, json={"admin_key": ADMIN_KEY})  # só a chave
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["connected"] and s["url"] == "http://hangarllm:4000" and s["discovered"]["container"] == "hangarllm-hangarllm-1"
    assert {n for n, _ in joined} == {"hangar_agents", "hangar_jobs"} and all(a == ["hangarllm"] for _, a in joined)
