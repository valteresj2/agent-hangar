"""Login da extensão do VS Code (portal + PKCE, código de uso único) e o download do .vsix."""
import base64
import hashlib
import secrets

from app import main as app_main
from app.db import SessionLocal
from app.models import ApiKey

from .conftest import ADMIN
from .test_access import _session


def _pkce():
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _user(client, uniq):
    email = f"{uniq('dev')}@acme.com"
    team = client.post("/api/teams", headers=ADMIN, json={"name": uniq("T")}).json()["slug"]
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": email, "role": "developer"})
    return email, _session(email)


def test_pkce_flow_creates_personal_key(client, uniq):
    email, h = _user(client, uniq)
    verifier, challenge = _pkce()
    r = client.post("/api/vscode/authorize", headers=h, json={"challenge": challenge, "state": "estado-123", "device": "VS Code em pc<1>"})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert r.json()["redirect"] == "vscode://agent-hangar.agent-hangar/auth" and r.json()["state"] == "estado-123"

    assert client.post("/api/auth/vscode/token", json={"code": code, "verifier": "outro"}).status_code == 400
    t = client.post("/api/auth/vscode/token", json={"code": code, "verifier": verifier})
    assert t.status_code == 200, t.text
    tok = t.json()
    assert tok["user"]["email"] == email
    me = client.get("/api/me", headers={"Authorization": f"Bearer {tok['token']}"}).json()
    assert me["user"]["email"] == email  # age como a pessoa
    with SessionLocal() as db:
        k = db.get(ApiKey, tok["key_id"])
        assert k.scopes == ["user"] and k.client == "vscode-ext" and k.name == "VS Code · VS Code em pc1"
    # uso único
    assert client.post("/api/auth/vscode/token", json={"code": code, "verifier": verifier}).status_code == 400


def test_authorize_needs_a_real_user_and_valid_input(client, uniq):
    _, h = _user(client, uniq)
    _, challenge = _pkce()
    assert client.post("/api/vscode/authorize", headers=ADMIN, json={"challenge": challenge, "state": "estado-123"}).status_code == 403
    assert client.post("/api/vscode/authorize", headers=h, json={"challenge": "curto", "state": "estado-123"}).status_code == 400
    assert client.post("/api/vscode/authorize", json={"challenge": challenge, "state": "estado-123"}).status_code == 401
    assert client.post("/api/auth/vscode/token", json={"code": "forjado.abc", "verifier": "x"}).status_code == 400


def test_vsix_download(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "DOWNLOADS", str(tmp_path))
    assert client.get("/downloads/agent-hangar-vscode.vsix").status_code == 404
    (tmp_path / "agent-hangar-vscode.vsix").write_bytes(b"PK\x03\x04vsix")
    r = client.get("/downloads/agent-hangar-vscode.vsix")
    assert r.status_code == 200 and r.content.startswith(b"PK") and "agent-hangar-vscode.vsix" in r.headers["content-disposition"]
