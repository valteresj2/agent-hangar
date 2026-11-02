# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Digital employee externo: um worker seu busca as tarefas pelo heartbeat, pede a mesma alçada antes de agir, e a
plataforma continua dona da fila, das decisões, do custo e do histórico."""
from app.services import employee_tasks as tasksmod

from .test_employees import assign, env, hire, make_active, open_request, rt, task, work  # noqa: F401


def _hb(client, token, **body):
    return client.post("/hooks/worker/heartbeat", headers={"Authorization": f"Bearer {token}"}, json=body)


def _call(client, token, tid, what, body):
    return client.post(f"/hooks/worker/tasks/{tid}/{what}", headers={"Authorization": f"Bearer {token}"}, json=body)


def test_external_worker_takes_tasks_asks_the_gate_and_reports(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    h = env["h"]["own"]
    assert client.put(f"/api/employees/{slug}/runtime", headers=env["h"]["out"], json={"runtime": "external"}).status_code in (403, 404)
    r = client.put(f"/api/employees/{slug}/runtime", headers=h, json={"runtime": "external"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token.startswith("ewk_") and r.json()["runtime"] == "external"
    assert "token" not in client.get(f"/api/employees/{slug}", headers=h).json()["external"]
    tid = assign(client, env, slug, "renove o contrato da ACME")
    calls = len(rt.calls) if hasattr(rt, "calls") else None
    work()  # o executor da plataforma não toca nas tarefas de um funcionário externo
    assert task(client, env, tid)["status"] == "new"
    if calls is not None:
        assert len(rt.calls) == calls
    # sem token, ou com um inválido: nada
    assert client.post("/hooks/worker/heartbeat", json={}).status_code == 401
    assert _hb(client, "ewk_nope").status_code == 401
    hb = _hb(client, token, worker={"name": "meu-worker", "version": "1.0"}).json()
    assert hb["employee"] == slug and hb["task"]["id"] == tid and hb["task"]["messages"][0]["role"] == "user"
    assert "ACME" in hb["task"]["messages"][0]["content"]
    assert task(client, env, tid)["status"] == "in_progress"
    assert _hb(client, token).json()["task"] is None  # uma tarefa só é entregue uma vez
    ext = client.get(f"/api/employees/{slug}", headers=h).json()["external"]
    assert ext["online"] and ext["worker"]["name"] == "meu-worker"
    # a ação que muda algo fora passa pela alçada: espera a aprovação e a tarefa sai do worker
    args = {"to": "ana@cliente.com", "body": "Olá"}
    g = _call(client, token, tid, "gate", {"tool": "send_email", "args": args, "rationale": "avisar a cliente"}).json()
    assert g["status"] == "waiting" and g["action_type"] == "send_external"
    assert task(client, env, tid)["status"] == "waiting_human"
    assert _call(client, token, tid, "result", {"status": "done", "result": "x"}).status_code == 409
    req = open_request(client, env, tid)
    assert client.post(f"/api/decisions/{req['id']}", headers=env["h"]["mgr"], json={"decision": "approve"}).status_code == 200
    hb = _hb(client, token).json()  # volta pelo heartbeat, com a decisão
    assert hb["task"]["id"] == tid and any(d["id"] == req["id"] and d["decision"] == "approve" for d in hb["task"]["decisions"])
    assert _call(client, token, tid, "gate", {"tool": "send_email", "args": args}).json()["status"] == "allowed"
    assert _call(client, token, tid, "gate", {"tool": "send_email", "args": args}).json()["status"] == "waiting"  # vale uma vez
    hb = _hb(client, token).json()
    assert hb["task"] is None  # está esperando a nova aprovação
    req2 = open_request(client, env, tid)
    client.post(f"/api/decisions/{req2['id']}", headers=env["h"]["mgr"], json={"decision": "reject", "reason": "não precisa"})
    hb = _hb(client, token).json()
    assert hb["task"]["id"] == tid
    p = _call(client, token, tid, "progress", {"note": "e-mail enviado", "cost_usd": 0.01, "tokens": 100}).json()
    assert p["cost_usd"] == 0.01 and not p["stop"]
    d = _call(client, token, tid, "result", {"status": "done", "result": "Contrato renovado e cliente avisada.",
                                              "cost_usd": 0.02, "tokens": 50}).json()
    assert d["status"] == "done"
    t = task(client, env, tid)
    assert t["status"] == "done" and t["result"].startswith("Contrato renovado") and abs(t["cost_usd"] - 0.03) < 1e-9
    kinds = [e["kind"] for e in t["events"]]
    for k in ("run", "gate", "human_request", "decision", "note", "done"):
        assert k in kinds, k
    # de volta para a plataforma: o token morre e a fila volta a ser do executor
    assert client.put(f"/api/employees/{slug}/runtime", headers=h, json={"runtime": "hangar"}).json()["runtime"] == "hangar"
    assert _hb(client, token).status_code == 401


def test_worker_failure_and_a_stuck_task_goes_back_to_the_queue(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    other = hire(client, env, name=f"Outro {env['n']}")
    make_active(client, env, other, rt)
    token = client.put(f"/api/employees/{slug}/runtime", headers=env["h"]["own"], json={"runtime": "external"}).json()["token"]
    tid = assign(client, env, slug, "tarefa 1")
    assert _hb(client, token).json()["task"]["id"] == tid
    # o worker de um funcionário não mexe na tarefa de outro
    otid = assign(client, env, other, "do outro")
    assert _call(client, token, otid, "result", {"status": "done"}).status_code == 401
    # rotate: o token antigo deixa de valer
    new = client.put(f"/api/employees/{slug}/runtime", headers=env["h"]["own"], json={"runtime": "external", "rotate": True}).json()["token"]
    assert new != token and _hb(client, token).status_code == 401
    # o worker some: a varredura devolve a tarefa à fila
    from datetime import timedelta

    from app.db import SessionLocal
    from app.models import EmployeeTask, now
    with SessionLocal() as db:
        t = db.get(EmployeeTask, tid)
        t.started_at = now() - timedelta(hours=3)
        db.commit()
        tasksmod.sweep(db)
    assert task(client, env, tid)["status"] == "new"
    with SessionLocal() as db:
        t = db.get(EmployeeTask, tid)
        t.not_before = None
        db.commit()
    assert _hb(client, new).json()["task"]["id"] == tid
    r = _call(client, new, tid, "result", {"status": "failed", "error": "o sistema do cliente caiu"}).json()
    assert r["status"] == "failed"
    assert task(client, env, tid)["error"] == "o sistema do cliente caiu"


def test_worker_agui_round_uses_the_employee_brain_and_bills_the_task(client, env, rt, monkeypatch):
    """O VS Code (ou outro worker) pensa com o próprio funcionário por AG-UI: o stream do runtime passa intacto, o custo
    entra na tarefa, e as ferramentas do posto de trabalho têm o tipo certo na alçada."""
    import json

    import httpx

    from app import deploy
    from app.routers import employees as router
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    token = client.put(f"/api/employees/{slug}/runtime", headers=env["h"]["own"], json={"runtime": "external"}).json()["token"]
    tid = assign(client, env, slug, "treine um modelo no bank-full")
    assert _hb(client, token).json()["task"]["id"] == tid
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["headers"], seen["body"] = str(req.url), dict(req.headers), json.loads(req.content)
        events = [{"type": "RUN_STARTED"},
                  {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "run_command"},
                  {"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"command": "python --version"}'},
                  {"type": "TOOL_CALL_END", "toolCallId": "c1"},
                  {"type": "CUSTOM", "name": "hangar.usage", "value": {"total_tokens": 1200, "cost_usd": 0.04}},
                  {"type": "RUN_FINISHED"}]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join(f"data: {json.dumps(e)}\n\n" for e in events).encode())
    real = httpx.AsyncClient
    monkeypatch.setattr(router.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(deploy, "ensure_up", lambda s, e: None)
    monkeypatch.setattr(deploy, "internal_url", lambda s, e: f"http://agent-{s}-{e}:8000")
    body = {"threadId": f"task-{tid}", "runId": "r1", "messages": [{"id": "m1", "role": "user", "content": "comece"}],
            "tools": [{"name": "run_command", "description": "terminal", "parameters": {"type": "object"}}]}
    assert _call(client, "ewk_nope", tid, "agui", body).status_code == 401
    r = _call(client, token, tid, "agui", body)
    assert r.status_code == 200, r.text
    frames = [json.loads(x[6:]) for x in r.text.split("\n") if x.startswith("data: ")]
    assert [f["type"] for f in frames][:2] == ["RUN_STARTED", "TOOL_CALL_START"]
    assert frames[-1]["name"] == "hangar.task" and frames[-1]["value"]["status"] == "in_progress"
    assert seen["url"] == f"http://agent-{slug}-prod:8000/agui"
    assert seen["headers"]["x-hangar-task"] == str(tid) and seen["headers"]["x-channel"] == "employee"
    assert seen["body"]["tools"][0]["name"] == "run_command"
    assert abs(task(client, env, tid)["cost_usd"] - 0.04) < 1e-9
    # o posto de trabalho no VS Code: comando é run_code, publicar no GitHub é publish, ler é read
    from app.db import SessionLocal
    from app.services import employee_gate
    with SessionLocal() as db:
        kinds = {n: employee_gate.classify(db, f"vscode:{n}").action_type for n in ("workspace_read_file", "run_command", "publish_github")}
    assert kinds == {"workspace_read_file": "read", "run_command": "run_code", "publish_github": "publish"}
    g = _call(client, token, tid, "gate", {"tool": "vscode:publish_github", "args": {"repo": "bank-ml", "public": True}}).json()
    assert g["status"] == "waiting" and g["action_type"] == "publish"
    # a tarefa saiu do worker (espera a decisão): a rodada AG-UI não roda mais
    assert _call(client, token, tid, "agui", body).status_code == 409
