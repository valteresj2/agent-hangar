"""Contas locais: usuário e senha (hash scrypt), bloqueio contra força bruta, troca e redefinição de senha."""
import pytest

from app import auth, config

from .conftest import ADMIN


@pytest.fixture()
def local(client, uniq):
    name = uniq("maria").lower()
    r = client.post("/api/users", headers=ADMIN, json={"username": name, "password": "Segredo@123", "org_role": "admin"})
    assert r.status_code == 200, r.text
    yield name, r.json()
    client.cookies.clear()
    auth._FAILS.clear()


def _login(client, user, pw):
    return client.post("/api/auth/password", json={"username": user, "password": pw})


def test_password_hash_is_not_the_password():
    h = auth.hash_password("Segredo@123")
    assert h.startswith("scrypt$") and "Segredo" not in h
    assert auth.verify_password("Segredo@123", h) and not auth.verify_password("errada", h)
    with pytest.raises(ValueError):
        auth.hash_password("curta")


def test_local_admin_logs_in(client, local):
    name, u = local
    assert u["username"] == name and u["has_password"] and u["email"] == f"{name}@local"
    assert client.get("/api/auth/providers").json()["password_login"]
    r = _login(client, name, "Segredo@123")
    assert r.status_code == 200 and auth.SESSION_COOKIE in r.cookies
    me = client.get("/api/me").json()
    assert me["is_admin"] and me["user"]["username"] == name


def test_wrong_password_and_lockout(client, local):
    name, _ = local
    assert _login(client, "nao-existe", "x" * 10).status_code == 403
    for _ in range(5):
        assert _login(client, name, "errada123").status_code == 403
    r = _login(client, name, "Segredo@123")  # certa, mas bloqueada
    assert r.status_code == 403 and "tentativas" in r.json()["detail"]


def test_change_and_reset_password(client, local):
    name, u = local
    _login(client, name, "Segredo@123")
    csrf = {"X-CSRF-Token": client.cookies.get(auth.CSRF_COOKIE)}
    assert client.post("/api/me/password", headers=csrf, json={"current": "errada", "new": "NovaSenha1"}).status_code == 403
    assert client.post("/api/me/password", headers=csrf, json={"current": "Segredo@123", "new": "NovaSenha1"}).status_code == 200
    client.cookies.clear()
    assert _login(client, name, "NovaSenha1").status_code == 200
    # admin redefine: a sessão antiga cai
    assert client.patch(f"/api/users/{u['id']}", headers=ADMIN, json={"password": "OutraSenha9"}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert _login(client, name, "OutraSenha9").status_code == 200


def test_deactivated_and_disabled(client, local, monkeypatch):
    name, u = local
    client.patch(f"/api/users/{u['id']}", headers=ADMIN, json={"active": False})
    assert _login(client, name, "Segredo@123").status_code == 403
    monkeypatch.setattr(config, "LOCAL_LOGIN", False)
    assert _login(client, name, "Segredo@123").status_code == 403
    assert not client.get("/api/auth/providers").json()["password_login"]


def test_username_rules(client, uniq):
    assert client.post("/api/users", headers=ADMIN, json={"username": "A B", "password": "Segredo@123"}).status_code == 400
    n = uniq("dup").lower()
    client.post("/api/users", headers=ADMIN, json={"username": n, "password": "Segredo@123"})
    assert client.post("/api/users", headers=ADMIN, json={"username": n, "password": "Segredo@123",
                                                          "email": f"{n}@x.com"}).status_code == 400
