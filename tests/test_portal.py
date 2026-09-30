"""Portal do usuário (/app) e console de admin (/ui só para admins); página Início (/api/me/home) por papel."""
from app import auth
from app.db import SessionLocal
from app.models import Agent, Team, TestRun, UsageEvent, User

from .conftest import ADMIN
from .test_access import org_setup  # noqa: F401  (fixture)


def _cookie(email: str | None = None, admin: bool = False) -> dict:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one() if email else None
        return {auth.SESSION_COOKIE: auth.create_session(db, u, admin=admin, label="teste") if admin else auth.create_session(db, u)}


def test_ui_is_admin_only(client, org_setup):  # noqa: F811
    s = org_setup
    client.cookies.clear()
    assert client.get("/ui/").status_code == 200  # sem sessão: tela de login
    client.cookies.update(_cookie(s["emails"]["dev"]))
    r = client.get("/ui/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/app/")
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/app/")
    p = client.get("/app/")
    assert p.status_code == 200 and "HANGAR_MODE = 'user'" in p.text and "/ui/home.js" in p.text
    client.cookies.clear()
    client.cookies.update(_cookie(admin=True))
    assert client.get("/ui/", follow_redirects=False).status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/ui/")
    client.cookies.clear()


def test_home_for_developer(client, org_setup):  # noqa: F811
    s, h = org_setup, org_setup["h"]
    with SessionLocal() as db:
        a = db.query(Agent).filter(Agent.slug == s["slug"]).one()
        db.add(TestRun(agent_id=a.id, version=a.current_version, status="failed", results=[], summary="0/1"))
        t = db.query(Team).filter(Team.slug == s["ta"]).one()
        t.budget_usd_month = 10.0
        dev = db.query(User).filter(User.email == s["emails"]["dev"]).one()
        db.add(UsageEvent(agent_id=a.id, env="prod", cost_usd=8.5, ok=False, user_id=dev.id))
        db.commit()
    home = client.get("/api/me/home", headers=h["dev"]).json()
    mine = {x["slug"]: x for x in home["agents"]}
    assert s["slug"] in mine and mine[s["slug"]]["can_edit"] and mine[s["slug"]]["errors_24h"] == 1
    texts = " | ".join(x["text"] for x in home["attention"])
    assert "teste reprovado" in texts and "erro(s)" in texts and "(85%)" in texts
    assert home["my_usage"]["requests"] == 1 and home["my_usage"]["by_agent"][0]["slug"] == s["slug"]
    assert home["teams"][0]["budget_state"] == "warn"


def test_home_requests_and_visibility(client, org_setup):  # noqa: F811
    s, h = org_setup, org_setup["h"]
    out = client.get("/api/me/home", headers=h["out"]).json()
    assert s["slug"] not in {a["slug"] for a in out["agents"]}  # agente de outro time não é "meu"
    assert client.post(f"/api/agents/{s['slug']}/access-requests", headers=h["out"], json={"reason": "relatórios"}).status_code == 200
    out = client.get("/api/me/home", headers=h["out"]).json()
    assert out["counts"]["my_pending"] == 1 and out["my_requests"]["access"][0]["status"] == "pending"
    maint = client.get("/api/me/home", headers=h["maint"]).json()
    assert maint["counts"]["to_decide"] >= 1 and maint["attention"][0]["link"] == "#/approvals"
    cons = client.get("/api/me/home", headers=h["cons"]).json()
    c = next(a for a in cons["agents"] if a["slug"] == s["slug"])
    assert not c["can_edit"] and c["can_consume"]
    assert not any("teste reprovado" in x["text"] for x in cons["attention"])  # consumer não vê alerta de teste


def test_home_keys(client, org_setup):  # noqa: F811
    h = org_setup["h"]
    k = client.post("/api/keys", headers=h["dev"], json={"name": "meu-token", "scopes": ["user"]}).json()
    keys = client.get("/api/me/home", headers=h["dev"]).json()["keys"]
    assert keys[0]["id"] == k["id"] and keys[0]["stale"]
    assert client.get("/api/me/home", headers=ADMIN).status_code == 200  # admin (token) também abre


def test_ui_scripts_share_no_global_names():
    """Os scripts da UI são clássicos e dividem o escopo global: um `const` repetido quebra o arquivo inteiro
    (foi o que derrubou a página Início com `reqPill` em org.js e home.js)."""
    import os
    import re
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "central", "app", "static")
    seen: dict[str, str] = {}
    for f in ("icons.js", "org.js", "home.js", "app.js"):
        src = open(os.path.join(static, f), encoding="utf-8").read()
        for name in re.findall(r"^(?:const|let|var|class|(?:async )?function)\s+([A-Za-z_$][\w$]*)", src, re.M):
            assert name not in seen, f"'{name}' declarado em {seen[name]} e em {f}"
            seen[name] = f
