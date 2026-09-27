"""Smoke E2E contra um Agent Hangar rodando de verdade (Docker real, sem LLM: tudo em modo mock).

    HANGAR_URL=http://localhost:8090 HANGAR_TOKEN=<admin> python tests/e2e/smoke.py

Cria agentes temporários (prefixo e2e-), exercita os 4 protocolos + MCP pelo gateway, um multiagente via A2A
interno, um job de harness (imagem base/mock), escopos de chave e a recusa de tokens internos forjados — e
apaga tudo no final. Sai com código != 0 na primeira falha.
"""
import os
import sys
import time
import uuid

import httpx

URL = os.environ.get("HANGAR_URL", "http://localhost:8090").rstrip("/")
TOKEN = os.environ["HANGAR_TOKEN"]
RUN = uuid.uuid4().hex[:6]
A, B, H = f"e2e-{RUN}-member", f"e2e-{RUN}-orch", f"e2e-{RUN}-harness"
c = httpx.Client(base_url=URL, timeout=300, headers={"Authorization": f"Bearer {TOKEN}"})
passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL {name} {detail}")
        raise SystemExit(1)
    passed += 1
    print(f"ok   {name}")


def ok(r: httpx.Response):
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:300]}")
    return r.json()


def main():
    check("health", ok(c.get("/api/health"))["status"] == "ok")
    doc = {"agents": [
        {"name": "E2E member", "slug": A, "objective": "eco", "final_output": "eco",
         "spec": {"instructions": "responda", "tools": [{"type": "builtin", "name": "calculator"}],
                  "tests": [{"input": "calc: 2+3", "expect_contains": "5"}]}},
        {"name": "E2E orchestrator", "slug": B, "objective": "delega", "final_output": "resposta",
         "spec": {"sub_agents": [A]}},
        {"name": "E2E harness", "slug": H, "objective": "executa", "final_output": "diff",
         "spec": {"harness": {"id": "claude-code"}}},
    ]}
    res = ok(c.post("/api/apply", json=doc))
    check("apply (gitops)", [r["action"] for r in res] == ["created"] * 3, res)
    check("apply idempotente", all(r["action"] == "unchanged" for r in ok(c.post("/api/apply", json=doc))))

    steps = ok(c.post(f"/api/agents/{B}/ship"))
    check("ship multiagente (membro primeiro)", [s["agent"] for s in steps if s["step"] == "prod"] == [A, B], steps)

    gw = f"/gw/{A}"
    r = ok(c.post(f"{gw}/v1/chat/completions", json={"messages": [{"role": "user", "content": "calc: 6*7"}]}))
    check("openai-compatible", "42" in r["choices"][0]["message"]["content"], r)
    r = ok(c.post(f"{gw}/a2a", json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {
        "message": {"kind": "message", "role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": "oi"}]}}}))
    check("a2a", "oi" in r["result"]["parts"][0]["text"], r)
    r = ok(c.get(f"{gw}/.well-known/agent.json"))
    check("agent card", r["url"].endswith(f"/gw/{A}/a2a"), r)
    r = ok(c.post(f"{gw}/acp/runs", json={"agent_name": A, "input": [
        {"role": "user", "parts": [{"content_type": "text/plain", "content": "oi"}]}]}))
    check("acp", r["status"] == "completed", r)
    mh = {"Accept": "application/json, text/event-stream"}
    r = ok(c.post(f"{gw}/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    check("mcp tools/list", len(r["result"]["tools"]) == 1, r)
    r = ok(c.post(f"/gw/{B}/v1/chat/completions", json={"messages": [{"role": "user", "content": "ping"}]}))
    check("multiagente via A2A interno", "delegado" in r["choices"][0]["message"]["content"], r)

    steps = ok(c.post(f"/api/agents/{H}/ship"))
    check("ship harness (job mock)", steps[-1]["step"] == "prod", steps)
    j = ok(c.post(f"/api/agents/{H}/job", json={"task": "crie um arquivo", "wait": True}))
    check("job harness", j["status"] == "passed" and "JOB_NOTES.md" in (j["diff"] or ""), j)
    r = ok(c.post(f"/gw/{H}/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                   "params": {"name": H, "arguments": {"message": "x"}}}))
    check("harness via mcp", not r["result"]["isError"], r)

    key = ok(c.post("/api/keys", json={"name": f"e2e-{RUN}", "scopes": ["invoke"], "agents": [A]}))
    kc = httpx.Client(base_url=URL, timeout=60, headers={"Authorization": f"Bearer {key['key']}"})
    check("chave invoke chama o agente", kc.post(f"{gw}/v1/chat/completions",
                                                 json={"messages": [{"role": "user", "content": "x"}]}).status_code == 200)
    check("chave invoke não chama outro", kc.post(f"/gw/{B}/v1/chat/completions", json={}).status_code == 403)
    check("chave invoke não administra", kc.get("/api/agents").status_code == 403)
    ok(c.delete(f"/api/keys/{key['id']}"))
    time.sleep(0.2)
    check("chave revogada", kc.post(f"{gw}/v1/chat/completions", json={}).status_code == 401)

    forged = httpx.post(f"{URL}/internal/gw/{A}/a2a", json={}, timeout=30,
                        headers={"X-Agent-Slug": B, "Authorization": f"Bearer {TOKEN}"})
    check("token interno forjado recusado", forged.status_code == 401, forged.text)
    check("dashboard interno exige credencial", httpx.get(f"{URL}/internal/dashboard/overview").status_code == 401)


if __name__ == "__main__":
    try:
        main()
        print(f"\n{passed} checks ok")
    finally:
        for slug in (B, A, H):
            c.delete(f"/api/agents/{slug}")
    sys.exit(0)
