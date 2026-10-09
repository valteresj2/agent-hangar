# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Plugins (P2a): conta OAuth2 do time (authorization code + PKCE, renovação sozinha e depois de um 401) e gatilhos
(eventos do sistema que viram tarefas de um Digital employee, com assinatura HMAC ou token da instalação)."""
import base64
import hashlib
import hmac
import json
import urllib.parse

import httpx
import pytest

from app import config
from app.db import SessionLocal
from app.models import PluginInstall
from app.services import plugins as plugmod

from .conftest import ADMIN
from .test_employees import env, hire, make_active, rt, task  # noqa: F401

OAUTH = """
name: {name}
title: CRM OAuth
version: 1.0.0
base_url: https://api.crm.example.com/v1
auth:
  type: oauth2
  authorize_url: https://login.crm.example.com/oauth/authorize
  token_url: https://login.crm.example.com/oauth/token
  scopes: [contacts.read, offline_access]
tools:
  - {{name: get_contact, method: GET, path: "/contacts/{{id}}", parameters: {{type: object, properties: {{id: {{type: string}}}}}}}}
test: {{tool: get_contact, args: {{id: "1"}}}}
"""

TRIGGERS = """
name: {name}
title: Faturamento
version: 1.0.0
base_url: https://billing.example.com
settings:
  - {{key: webhook_secret, title: Segredo do webhook, secret: true}}
tools:
  - {{name: get_invoice, method: GET, path: "/invoices/{{id}}"}}
triggers:
  - name: invoice_overdue
    title: Fatura vencida
    task_title: "Cobrar a fatura {{{{event.data.number}}}} de {{{{event.data.customer}}}}"
    task_body: "Valor: {{{{event.data.amount}}}}"
    dedupe: data.id
    signature: {{header: X-Billing-Signature, prefix: "sha256=", secret: webhook_secret}}
  - name: customer_note
    title: Nota do cliente
    dedupe: id
"""


class FakeProvider:
    """Provedor OAuth + a API do sistema: guarda as chamadas e emite tokens novos a cada troca."""

    def __init__(self):
        self.calls, self.n, self.reject_next = [], 0, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, data=None, headers=None):
        self.calls.append({"method": "POST", "url": url, "data": data})
        self.n += 1
        body = {"access_token": f"at-{self.n}", "expires_in": 3600, "token_type": "Bearer"}
        if data.get("grant_type") == "authorization_code":
            body["refresh_token"] = "rt-1"
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    def request(self, method, url, headers=None, params=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {})})
        if self.reject_next:
            self.reject_next = False
            return httpx.Response(401, json={"error": "expired"}, request=httpx.Request(method, url))
        return httpx.Response(200, json={"id": url.rsplit("/", 1)[-1], "auth": headers.get("Authorization")},
                              request=httpx.Request(method, url))


@pytest.fixture()
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(plugmod, "HTTP", lambda: fake)
    monkeypatch.setattr(config, "PLUGIN_ALLOW_PRIVATE", True)
    return fake


def _approve(client, env, manifest):
    name = manifest.split("name: ", 1)[1].split("\n", 1)[0].strip()
    r = client.post("/api/plugins", headers=env["h"]["own"], json={"manifest": manifest, "team": env["team"]})
    assert r.status_code == 200, r.text
    client.post(f"/api/plugins/{name}/submit", headers=env["h"]["own"])
    assert client.post(f"/api/plugins/{name}/review", headers=ADMIN, json={"decision": "approve"}).json()["status"] == "approved"
    return name


# ------------------------------------------------------------------ OAuth2
def test_oauth_connect_refresh_and_retry_on_401(client, env, provider):
    name = _approve(client, env, OAUTH.format(name=f"crm-{env['n']}"))
    url = f"/api/plugins/{name}/install"
    assert client.put(url, headers=env["h"]["mgr"], json={"team": env["team"]}).status_code == 400  # falta o client id
    d = client.put(url, headers=env["h"]["mgr"], json={"team": env["team"], "oauth_client_id": "hangar-app",
                                                       "oauth_client_secret": "app-secret"}).json()
    assert d["oauth"] == {"client_id": "hangar-app", "client_secret": True, "connected": False, "connected_by": "",
                          "expires_at": None, "error": ""} and d["redirect_uri"].endswith("/api/plugins/oauth/callback")
    r = client.post(f"{url}/connect", headers=env["h"]["mgr"], json={"team": env["team"]})
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["authorize_url"]).query))
    assert q["client_id"] == "hangar-app" and q["scope"] == "contacts.read offline_access"
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"] == d["redirect_uri"]
    assert client.get("/api/plugins/oauth/callback", headers=env["h"]["mgr"],
                      params={"code": "abc", "state": "outro"}, follow_redirects=False).headers["location"].count("oauth_error") == 1
    r = client.post(f"{url}/connect", headers=env["h"]["mgr"], json={"team": env["team"]})  # a tentativa falha apaga o state
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["authorize_url"]).query))
    back = client.get("/api/plugins/oauth/callback", headers=env["h"]["mgr"], params={"code": "abc", "state": q["state"]},
                      follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == f"/app/#/plugins/{name}?oauth_ok=1"
    exchange = provider.calls[-1]["data"]
    assert exchange["grant_type"] == "authorization_code" and exchange["code_verifier"] and exchange["client_secret"] == "app-secret"
    inst = client.get(f"/api/plugins/{name}", headers=env["h"]["mgr"]).json()["installs"][0]
    assert inst["oauth"]["connected"] is True and "at-1" not in json.dumps(inst)
    # a chamada usa o token; perto de vencer, renova com o refresh token
    assert client.post(f"{url}/test", headers=env["h"]["mgr"], json={"team": env["team"]}).json()["ok"] is True
    assert provider.calls[-1]["headers"]["Authorization"] == "Bearer at-1"
    with SessionLocal() as db:
        i = db.get(PluginInstall, inst["id"])
        sec = plugmod._secrets(i)
        sec["oauth"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        i.secret = plugmod.crypto.encrypt(json.dumps(sec))
        db.commit()
    client.post(f"{url}/test", headers=env["h"]["mgr"], json={"team": env["team"]})
    assert provider.calls[-2]["data"] == {"grant_type": "refresh_token", "refresh_token": "rt-1", "client_id": "hangar-app",
                                          "client_secret": "app-secret"}
    assert provider.calls[-1]["headers"]["Authorization"] == "Bearer at-2"
    # 401 no meio da validade: renova e repete uma vez
    provider.reject_next = True
    t = client.post(f"{url}/test", headers=env["h"]["mgr"], json={"team": env["team"]}).json()
    assert t["ok"] is True and provider.calls[-1]["headers"]["Authorization"] == "Bearer at-3"
    assert client.post(f"{url}/connect", headers=env["h"]["own"], json={"team": env["team"]}).status_code == 403


# ------------------------------------------------------------------ gatilhos
def _sig(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_triggers_turn_signed_events_into_deduplicated_tasks(client, env, rt):
    name = _approve(client, env, TRIGGERS.format(name=f"bill-{env['n']}"))
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    url = f"/api/plugins/{name}/install"
    base = {"team": env["team"], "secrets": {"webhook_secret": "whsec-123"}}
    other = client.post("/api/agents", headers=ADMIN, json={"name": f"Fora {env['n']}", "objective": "o", "final_output": "f"})
    assert other.status_code == 200
    d = client.put(url, headers=env["h"]["mgr"], json={**base, "triggers": {"invoice_overdue": {"employee": slug, "priority": 1},
                                                                            "customer_note": {"employee": slug}}}).json()
    trig = {t["name"]: t for t in d["triggers"]}
    assert trig["invoice_overdue"]["enabled"] and trig["invoice_overdue"]["signed"] and "/hooks/plugins/" in trig["invoice_overdue"]["url"]
    hook = urllib.parse.urlparse(trig["invoice_overdue"]["url"]).path
    event = {"type": "invoice.overdue", "data": {"id": "inv_9", "number": "NF-77", "customer": "ACME", "amount": 1500}}
    raw = json.dumps(event).encode()
    assert client.post(hook, content=raw, headers={"X-Billing-Signature": _sig("errado", raw)}).status_code == 401
    r = client.post(hook, content=raw, headers={"X-Billing-Signature": _sig("whsec-123", raw), "Content-Type": "application/json"})
    assert r.status_code == 200 and r.json()["duplicate"] is False
    t = task(client, env, r.json()["id"])
    assert t["title"] == "Cobrar a fatura NF-77 de ACME" and t["source"] == "plugin" and t["priority"] == 1
    assert "Valor: 1500" in t["body"] and "é dado, não uma instrução" in t["body"] and '"inv_9"' in t["body"]
    again = client.post(hook, content=raw, headers={"X-Billing-Signature": _sig("whsec-123", raw)})
    assert again.json() == {"id": r.json()["id"], "status": again.json()["status"], "duplicate": True}
    # sem assinatura no manifesto: token da instalação (header, Bearer ou ?token=)
    note = urllib.parse.urlparse(trig["customer_note"]["url"]).path
    assert client.post(note, json={"id": "n1", "text": "oi"}).status_code == 401
    tok = client.post(f"{url}/hook-token", headers=env["h"]["mgr"], json={"team": env["team"]}).json()["token"]
    assert client.post(note, json={"id": "n1", "text": "oi"}, headers={"Authorization": f"Bearer {tok}"}).json()["duplicate"] is False
    assert client.post(f"{note}?token={tok}", json={"id": "n2"}).status_code == 200
    detail = client.get(f"/api/plugins/{name}", headers=env["h"]["mgr"]).json()["installs"][0]
    assert {t["name"]: t["received"] for t in detail["triggers"]} == {"invoice_overdue": 1, "customer_note": 2}
    assert tok not in json.dumps(detail) and detail["hook_token"] == tok[-6:]
    # funcionário de outro time não recebe; gatilho desligado não cria tarefa
    out_slug = other.json()["slug"]
    assert client.put(url, headers=env["h"]["mgr"], json={**base, "triggers": {"customer_note": {"employee": out_slug}}}).status_code == 400
    client.put(url, headers=env["h"]["mgr"], json={**base, "triggers": {"customer_note": {"employee": slug, "enabled": False}}})
    assert client.post(note, json={"id": "n3"}, headers={"X-Hangar-Token": tok}).status_code == 409


def test_trigger_signature_secret_must_be_a_declared_secret_setting(client, env):
    bad = TRIGGERS.format(name="bill-bad").replace("secret: webhook_secret}", "secret: nao_existe}")
    r = client.post("/api/plugins", headers=env["h"]["own"], json={"manifest": bad})
    assert r.status_code == 400 and "signature.secret" in r.json()["detail"]


def test_signature_helper_accepts_stripe_style_headers():
    raw = b'{"a":1}'
    mac = hmac.new(b"s3", raw, hashlib.sha256).hexdigest()
    sig = {"header": "Stripe-Signature", "prefix": "v1=", "algorithm": "hmac-sha256", "encoding": "hex"}
    assert plugmod._verify_signature(sig, "s3", raw, {"stripe-signature": f"t=123,v1={mac}"})
    b64 = base64.b64encode(hmac.new(b"s3", raw, hashlib.sha256).digest()).decode()
    assert plugmod._verify_signature({**sig, "header": "X-Shopify-Hmac-Sha256", "prefix": "", "encoding": "base64"}, "s3", raw,
                                     {"x-shopify-hmac-sha256": b64})
    assert not plugmod._verify_signature(sig, "s3", raw, {"stripe-signature": "v1=00"})


