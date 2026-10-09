# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Decisões fora do portal (F3): botões do Slack na própria mensagem, link assinado no Teams e no e-mail, alerta antes
de expirar, resumo diário e prazos de tarefa (vence logo, atrasada, escalada) com o "% no prazo" valendo na carreira."""
import hashlib
import hmac
import json
import re
import time
import urllib.parse
from datetime import timedelta

import httpx
import pytest

from app import config
from app import services as svc
from app.db import SessionLocal
from app.models import AuditLog, Employee, EmployeeTask, HumanRequest, Organization, User, now
from app.services import employee_work as workmod
from app.services import notify

from .conftest import ADMIN
from .test_employees import assign, env, hire, make_active, open_request, rt, task, work  # noqa: F401

SECRET = "slack-signing-secret"


class FakeSlack:
    """API do Slack: guarda cada chamada e responde como o Slack (ids de usuário derivados do e-mail)."""

    def __init__(self):
        self.calls, self.emails = [], {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def uid(self, email):
        sid = "U" + hashlib.md5(email.encode()).hexdigest()[:8].upper()
        self.emails[sid] = email
        return sid

    def post(self, url, headers=None, json=None, data=None):
        body = json if json is not None else data
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method if "slack.com/api" in url else url, body))
        out = {"ok": True}
        if method == "auth.test":
            out["team"] = "Acme"
        elif method == "users.lookupByEmail":
            out["user"] = {"id": self.uid(body["email"])}
        elif method == "users.info":
            out["user"] = {"id": body["user"], "profile": {"email": self.emails.get(body["user"], "ghost@nowhere.com")}}
        elif method == "chat.postMessage":
            out.update(channel=f"D{body['channel']}", ts=f"{time.time():.6f}")
        return httpx.Response(200, json=out, request=httpx.Request("POST", url))

    def of(self, method):
        return [b for m, b in self.calls if m == method]


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, m):
        FakeSMTP.sent.append(m)


def _sync(fn, *args):
    with SessionLocal() as db:
        fn(db, *args)


@pytest.fixture()
def channels(monkeypatch):
    """Envio síncrono, Slack e SMTP simulados; no fim, a empresa volta sem canais (os outros testes não enviam nada)."""
    slack = FakeSlack()
    monkeypatch.setattr(notify, "_bg", _sync)
    monkeypatch.setattr(notify, "HTTP", lambda: slack)
    monkeypatch.setattr(notify, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    yield slack
    with SessionLocal() as db:
        db.get(Organization, 1).notify = None
        for u in db.query(User).filter(User.notify.is_not(None)):
            u.notify = None
        db.commit()


def _slack_on(client):
    r = client.put("/api/admin/notifications", headers=ADMIN,
                   json={"slack_bot_token": "xoxb-test-token", "slack_signing_secret": SECRET})
    assert r.status_code == 200, r.text
    assert r.json()["slack"]["configured"] is True and "xoxb" not in json.dumps(r.json())  # segredos não voltam


def _signed(payload: dict, secret=SECRET, ts=None) -> tuple[bytes, dict]:
    raw = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = str(int(ts or time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                 "Content-Type": "application/x-www-form-urlencoded"}


def _click(client, slack, email, verb, rid, **extra):
    raw, h = _signed({"type": "block_actions", "user": {"id": slack.uid(email)}, "trigger_id": "trig",
                      "response_url": "https://hooks.slack.com/actions/T/1/x",
                      "actions": [{"action_id": f"hangar:{verb}", "value": str(rid)}], **extra})
    return client.post("/hooks/slack/interactions", content=raw, headers=h)


def _submit(client, slack, email, verb, rid, reason="", payload=None):
    values = {"reason": {"v": {"value": reason}}}
    if payload is not None:
        values["payload"] = {"v": {"value": payload}}
    raw, h = _signed({"type": "view_submission", "user": {"id": slack.uid(email)},
                      "view": {"callback_id": f"hangar:{verb}", "private_metadata": json.dumps({"r": rid}),
                               "state": {"values": values}}})
    return client.post("/hooks/slack/interactions", content=raw, headers=h)


def _waiting(client, env, rt, **hire_over):
    slug = hire(client, env, **hire_over)
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, 'use send_email {"to": "ana@cliente.com", "body": "Olá"}')
    work()
    return slug, tid, open_request(client, env, tid)


# ------------------------------------------------------------------ Slack
def test_slack_dm_has_buttons_and_approving_in_the_message_resumes_the_task(client, env, rt, channels):
    slack = channels
    _slack_on(client)
    slug, tid, req = _waiting(client, env, rt)
    msg = next(m for m in slack.of("chat.postMessage") if f"#{req['id']}" in m["text"])
    assert msg["channel"] == slack.uid(env["em"]["mgr"])  # DM para quem está com o pedido
    actions = next(b for b in msg["blocks"] if b["type"] == "actions")["elements"]
    assert [a["action_id"] for a in actions] == ["hangar:approve", "hangar:edit", "hangar:reject", "hangar:open"]
    assert "ana@cliente.com" in json.dumps(msg["blocks"])  # a ação exata está na mensagem
    # assinatura errada ou velha: recusado
    raw, h = _signed({"type": "block_actions"}, secret="outro")
    assert client.post("/hooks/slack/interactions", content=raw, headers=h).status_code == 401
    raw, h = _signed({"type": "block_actions"}, ts=time.time() - 600)
    assert client.post("/hooks/slack/interactions", content=raw, headers=h).status_code == 401
    # alguém de outro time clica: não decide, recebe o aviso só para ele
    assert _click(client, slack, env["em"]["out"], "approve", req["id"]).status_code == 200
    url, eph = slack.calls[-1]
    assert url.startswith("https://hooks.slack.com/") and eph["response_type"] == "ephemeral"
    assert "não pode decidir" in eph["text"]
    assert task(client, env, tid)["status"] == "waiting_human"
    # o gestor aprova na própria mensagem
    assert _click(client, slack, env["em"]["mgr"], "approve", req["id"]).status_code == 200
    t = task(client, env, tid)
    r = next(x for x in t["requests"] if x["id"] == req["id"])
    assert r["decision"] == "approve" and r["decided_by"] == env["em"]["mgr"]
    upd = slack.of("chat.update")[-1]
    assert all(b["type"] != "actions" for b in upd["blocks"]) and "Aprovado por" in json.dumps(upd["blocks"])
    work()
    assert task(client, env, tid)["status"] == "done"
    with SessionLocal() as db:
        via = db.query(AuditLog).filter_by(action="employee.decision.channel", target=slug).one()
        assert via.actor == env["em"]["mgr"] and "via slack" in via.detail


def test_slack_edit_and_reject_open_a_modal_and_decide_on_submit(client, env, rt, channels):
    slack = channels
    _slack_on(client)
    slug, tid, req = _waiting(client, env, rt)
    assert _click(client, slack, env["em"]["mgr"], "edit", req["id"]).status_code == 200
    view = slack.of("views.open")[-1]["view"]
    assert view["callback_id"] == "hangar:edit" and "ana@cliente.com" in json.dumps(view)
    bad = _submit(client, slack, env["em"]["mgr"], "edit", req["id"], payload="{not json")
    assert bad.json()["response_action"] == "errors"
    ok = _submit(client, slack, env["em"]["mgr"], "edit", req["id"], reason="tom mais formal",
                 payload=json.dumps({"to": "ana@cliente.com", "body": "Prezada Ana"}))
    assert ok.status_code == 200 and not ok.content
    r = next(x for x in task(client, env, tid)["requests"] if x["id"] == req["id"])
    assert r["decision"] == "approve_edited" and r["edited_payload"]["body"] == "Prezada Ana"
    # recusar com motivo, pelo modal
    tid2 = assign(client, env, slug, 'use send_email {"to": "bob@cliente.com"}')
    work()
    req2 = open_request(client, env, tid2)
    _click(client, slack, env["em"]["mgr"], "reject", req2["id"])
    assert slack.of("views.open")[-1]["view"]["callback_id"] == "hangar:reject"
    _submit(client, slack, env["em"]["mgr"], "reject", req2["id"], reason="cliente pediu silêncio")
    r2 = next(x for x in task(client, env, tid2)["requests"] if x["id"] == req2["id"])
    assert r2["decision"] == "reject" and r2["reason"] == "cliente pediu silêncio"
    # decidir no portal também atualiza a mensagem no Slack
    tid3 = assign(client, env, slug, 'use send_email {"to": "cid@cliente.com"}')
    work()
    req3 = open_request(client, env, tid3)
    n = len(slack.of("chat.update"))
    client.post(f"/api/decisions/{req3['id']}", headers=env["h"]["mgr"], json={"decision": "approve"})
    assert len(slack.of("chat.update")) == n + 1


# ------------------------------------------------------------------ link assinado (e-mail e Teams)
def test_email_link_shows_on_get_and_decides_only_on_post(client, env, rt, channels, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    slug, tid, req = _waiting(client, env, rt)
    mail = next(m for m in FakeSMTP.sent if f"#{req['id']}" in m["Subject"])
    assert mail["To"] == env["em"]["mgr"]
    links = re.findall(r"https?://\S+/hooks/decide/[\w.\-]+\?d=\w+", mail.get_body(("plain",)).get_content())
    assert {x.rsplit("=", 1)[1] for x in links} == {"approve", "edit", "reject"}
    path = urllib.parse.urlparse(links[0]).path
    page = client.get(path)
    assert page.status_code == 200 and "ana@cliente.com" in page.text and page.headers["cache-control"] == "no-store"
    assert task(client, env, tid)["status"] == "waiting_human"  # abrir o link (ou o antivírus abrir) não decide
    # link adulterado ou de outra pessoa
    tok = path.rsplit("/", 1)[1]
    rid, uid, exp, mac = tok.split(".")
    with SessionLocal() as db:
        out_id = db.query(User).filter(User.email == env["em"]["out"]).one().id
    forged = f"{rid}.{out_id}.{exp}.{mac}"
    assert client.post(f"/hooks/decide/{forged}", data={"decision": "approve"}).status_code == 403
    assert client.post(f"/hooks/decide/{notify.sign(req['id'], out_id)}", data={"decision": "approve"}).status_code == 403
    assert client.get(f"/hooks/decide/{notify.sign(req['id'], int(uid), ttl_h=-1)}").status_code == 403  # vencido
    r = client.post(path, data={"decision": "reject", "reason": "agora não"})
    assert r.status_code == 200 and "Recusado por" in r.text
    assert next(x for x in task(client, env, tid)["requests"] if x["id"] == req["id"])["decision"] == "reject"
    assert client.post(path, data={"decision": "approve"}).status_code == 409  # já decidido


def test_teams_card_uses_personal_webhook_with_signed_buttons(client, env, rt, channels, monkeypatch):
    from app.services import schedules
    posted = []

    class FakeTeams:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **k):
            posted.append((url, json))
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(schedules, "HTTP", lambda: FakeTeams())
    monkeypatch.setattr(config, "SCHEDULE_ALLOW_PRIVATE_WEBHOOKS", True)
    hook = "https://acme.webhook.office.com/workflows/123"
    r = client.put("/api/me/notifications", headers=env["h"]["mgr"], json={"channel": "teams", "teams_webhook": hook})
    assert r.json()["route"] == "teams" and r.json()["teams_webhook"] is True and hook not in r.text
    slug, tid, req = _waiting(client, env, rt)
    url, body = next((u, b) for u, b in posted if u == hook and f"#{req['id']}" in json.dumps(b))
    card = body["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert [a["title"] for a in card["actions"]] == ["Aprovar", "Editar", "Recusar", "Abrir no portal"]
    assert "/hooks/decide/" in card["actions"][0]["url"]


# ------------------------------------------------------------------ preferências e admin
def test_preferences_and_admin_settings(client, env, channels, monkeypatch):
    me = client.get("/api/me/notifications", headers=env["h"]["mgr"]).json()
    assert me["channel"] == "auto" and me["route"] is None and me["available"] == []
    assert client.post("/api/me/notifications/test", headers=env["h"]["mgr"]).status_code == 400  # nenhum canal
    assert client.put("/api/me/notifications", headers=env["h"]["mgr"], json={"channel": "pombo"}).status_code == 400
    bad = client.put("/api/me/notifications", headers=env["h"]["mgr"], json={"teams_webhook": "http://10.0.0.5/hook"})
    assert bad.status_code == 400  # webhook para a rede interna
    assert client.get("/api/admin/notifications", headers=env["h"]["mgr"]).status_code == 403
    assert client.put("/api/admin/notifications", headers=ADMIN, json={"slack_bot_token": "nope"}).status_code == 400
    assert client.put("/api/admin/notifications", headers=ADMIN, json={"digest_hour": 30}).status_code == 400
    a = client.get("/api/admin/notifications", headers=ADMIN).json()
    assert a["slack"]["interactions_url"].endswith("/hooks/slack/interactions") and "users:read.email" in a["slack"]["manifest"]
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    me = client.put("/api/me/notifications", headers=env["h"]["mgr"], json={"channel": "slack"}).json()
    assert me["route"] == "email"  # escolheu Slack, mas sem Slack na empresa: cai no que existe
    assert client.post("/api/me/notifications/test", headers=env["h"]["mgr"]).json()["via"] == "email"
    assert FakeSMTP.sent[-1]["To"] == env["em"]["mgr"]
    client.put("/api/me/notifications", headers=env["h"]["mgr"], json={"channel": "off"})
    assert client.get("/api/me/notifications", headers=env["h"]["mgr"]).json()["route"] is None


# ------------------------------------------------------------------ alerta de expiração e resumo diário
def test_expiry_warning_once_and_daily_digest_once(client, env, rt, channels, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    client.put("/api/admin/notifications", headers=ADMIN, json={"digest_hour": -1})  # sem resumo até a hora certa
    slug, tid, req = _waiting(client, env, rt)
    with SessionLocal() as db:
        r = db.get(HumanRequest, req["id"])
        r.created_at, r.expires_at = now() - timedelta(hours=3), now() + timedelta(minutes=30)
        db.commit()
        n = len(FakeSMTP.sent)
        assert notify.sweep(db)["reminded"] == 1
        assert notify.sweep(db)["reminded"] == 0  # só uma vez
    warn = FakeSMTP.sent[n]
    assert warn["To"] == env["em"]["mgr"] and "Vai expirar" in warn.get_body(("plain",)).get_content()
    client.put("/api/admin/notifications", headers=ADMIN, json={"digest_hour": 0})
    with SessionLocal() as db:
        n = len(FakeSMTP.sent)
        assert notify.digests(db) >= 1
        mine = [m for m in FakeSMTP.sent[n:] if m["To"] == env["em"]["mgr"]]
        assert len(mine) == 1 and f"#{req['id']}" in mine[0].get_body(("plain",)).get_content()
        assert notify.digests(db) == 0  # uma vez por dia
    client.put("/api/me/notifications", headers=env["h"]["bk"], json={"digest": False})
    assert client.get("/api/me/notifications", headers=env["h"]["bk"]).json()["digest"] is False


# ------------------------------------------------------------------ prazos de tarefa
def test_task_deadline_soon_overdue_and_escalated(client, env, rt, channels, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    slug, tid, req = _waiting(client, env, rt)  # parada esperando decisão: não termina sozinha
    with SessionLocal() as db:
        t = db.get(EmployeeTask, tid)
        t.created_at, t.due_at, t.priority = now() - timedelta(hours=4), now() + timedelta(minutes=20), 3
        db.commit()
        assert notify.due_sweep(db)["due_soon"] == 1
        t = db.get(EmployeeTask, tid)
        assert t.due_state == "soon" and t.priority == 1  # sobe na fila
        sent = [m["To"] for m in FakeSMTP.sent if "vence" in m["Subject"]]
        assert sent == [env["em"]["mgr"]]
        t.due_at = now() - timedelta(minutes=1)
        db.commit()
        assert notify.due_sweep(db)["overdue"] == 1 and notify.due_sweep(db)["overdue"] == 0
        late = {m["To"] for m in FakeSMTP.sent if "atrasada" in m["Subject"]}
        assert late == {env["em"]["mgr"], env["em"]["req"]}  # gestor e quem pediu
        t = db.get(EmployeeTask, tid)
        t.due_at = now() - timedelta(hours=3)
        db.commit()
        assert notify.due_sweep(db)["due_escalated"] == 1
        esc = {m["To"] for m in FakeSMTP.sent if "escalada" in m["Subject"]}
        assert env["em"]["bk"] in esc and env["em"]["mgr"] not in esc  # substituto e mantenedores
    d = task(client, env, tid)
    assert d["due_state"] == "escalated" and [e["payload"]["stage"] for e in d["events"] if e["kind"] == "due"] == \
        ["soon", "overdue", "escalated"]
    assert client.get(f"/api/employees/{slug}", headers=env["h"]["own"]).json()["overdue_tasks"] == 1
    with SessionLocal() as db:
        e = db.query(Employee).filter(Employee.agent_id == svc.get_agent(db, slug).id).one()
        assert workmod.kpi_actuals(db, e)["on_time_rate"] == 0.0  # vencida e aberta conta contra o "% no prazo"


def test_on_time_rate_counts_in_the_career(client, env, rt, monkeypatch):
    monkeypatch.setattr(workmod, "ON_TIME_MIN", 1)
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    r = client.post(f"/api/employees/{slug}/tasks", headers=env["h"]["req"],
                    json={"title": "relatório", "body": "faça", "due_at": (now() - timedelta(minutes=5)).isoformat()})
    work()
    d = task(client, env, r.json()["id"])
    assert d["status"] == "done" and any(e["kind"] == "due" and e["payload"]["stage"] == "late" for e in d["events"])
    crit = {c["key"]: c for c in client.get(f"/api/employees/{slug}/career", headers=env["h"]["own"]).json()["criteria"]}
    assert crit["on_time"]["value"] == 0.0 and crit["on_time"]["ok"] is False
