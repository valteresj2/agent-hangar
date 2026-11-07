# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""O computador da pessoa como desktop do Digital employee (o app Agent Hangar Desktop como posto): as ações na tela
pedem a alçada no /gate (desktop:<ação>) com as mesmas regras do desktop da plataforma — o clique que confirma espera
a decisão com a captura no pedido e acontece onde a pessoa aprovou, o "Sim" logo depois já está coberto, a confirmação
repetida é recusada, o segredo vai só para o posto e cada ação fica na linha do tempo."""
import base64

from app.db import SessionLocal
from app.models import Employee, TaskFile
from app.services import desktop
from app.services.employee_external import _hash

from .conftest import ADMIN
from .test_employees import assign, env, hire, make_active, open_request, rt, task, work  # noqa: F401
from .test_external_worker import _call, _hb

PNG = base64.b64encode(b"\x89PNG janela do bloco de notas").decode()


def _worker(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    token = client.put(f"/api/employees/{slug}/runtime", headers=env["h"]["own"],
                       json={"runtime": "external", "rotate": True}).json()["token"]
    tid = assign(client, env, slug, "escreva a nota da reunião e salve")
    hb = _hb(client, token, worker={"name": "Computador (PC-ANA)", "apps": "Bloco de Notas"}).json()
    assert hb["task"]["id"] == tid
    return slug, token, tid


def _gate(client, token, tid, action, args, shot=""):
    r = _call(client, token, tid, "gate", {"tool": f"desktop:{action}", "args": args, "rationale": "salvar a nota",
                                           **({"screenshot": shot} if shot else {})})
    assert r.status_code == 200, r.text
    return r.json()


def _desktop_events(client, env, tid):
    return [e["payload"] for e in task(client, env, tid)["events"] if e["kind"] == "desktop"]


def test_local_computer_actions_go_through_the_desktop_rules(client, env, rt):
    slug, token, tid = _worker(client, env, rt)
    win = "nota.txt - Bloco de Notas"
    g = _gate(client, token, tid, "open", {"app": "Bloco de Notas", "window": win})
    assert g["status"] == "allowed" and g["event"]
    # digitar e clicar no que não confirma nada: liberado na hora, e cada ação fica na linha do tempo
    g = _gate(client, token, tid, "type", {"text": "Pauta: orçamento", "label": "Texto", "window": win})
    assert g["status"] == "allowed" and "text" not in g
    assert _gate(client, token, tid, "click", {"label": "Formatar", "x": 120, "y": 12, "window": win})["status"] == "allowed"
    evs = _desktop_events(client, env, tid)
    assert [e["action"] for e in evs] == ["open", "type", "click"]
    assert all(e["local"] and e["machine"] == "Computador (PC-ANA)" for e in evs)
    assert evs[1]["value"] == "Pauta: orçamento" and evs[1]["window"] == win
    # Ctrl+S salva: espera a decisão, com a captura da janela no pedido; a tarefa sai do posto
    g = _gate(client, token, tid, "key", {"key": "s", "modifiers": ["ctrl"], "window": win}, PNG)
    assert g["status"] == "waiting" and g["action_type"] == "write_internal"
    assert task(client, env, tid)["status"] == "waiting_human"
    req = open_request(client, env, tid)
    assert "Tela: tela-" in req["rationale"] and req["payload"] == {"key": "ctrl+s", "window": win}
    with SessionLocal() as db:
        f = db.query(TaskFile).filter(TaskFile.task_id == tid, TaskFile.name.like("tela-%")).one()
        assert f.size == len(base64.b64decode(PNG))
    client.post(f"/api/decisions/{req['id']}", headers=env["h"]["mgr"], json={"decision": "approve"})
    assert _hb(client, token).json()["task"]["id"] == tid  # volta pelo heartbeat
    g = _gate(client, token, tid, "key", {"key": "s", "modifiers": ["ctrl"], "window": win}, PNG)
    assert g["status"] == "allowed" and g["approved"] == req["id"]
    ev = _desktop_events(client, env, tid)[-1]
    assert ev["action"] == "key" and ev["target"] == "ctrl+s" and ev["approved"] == req["id"]
    # o posto conta a janela depois (a regra da nova tentativa compara)
    p = _call(client, token, tid, "progress", {"desktop": {"event": g["event"], "after": win},
                                               "tool": {"name": "desktop_key", "summary": "ctrl+s", "ok": True, "ms": 80}})
    assert p.status_code == 200
    assert _desktop_events(client, env, tid)[-1]["after"] == win
    # Return num diálogo de salvar confirma (e pede de novo); fora de um diálogo só passa de linha
    assert _gate(client, token, tid, "key", {"key": "Return", "window": win})["status"] == "allowed"
    assert _gate(client, token, tid, "key", {"key": "Return", "window": "Salvar como"}, PNG)["status"] == "waiting"
    req2 = open_request(client, env, tid)
    assert "Janela: Salvar como" in req2["rationale"]


def test_click_runs_where_approved_dialog_yes_is_covered_and_a_repeat_is_refused(client, env, rt):
    slug, token, tid = _worker(client, env, rt)
    erp = "ERP Legado 7.2"
    _gate(client, token, tid, "type", {"text": "88", "label": "Fatura:", "window": erp})
    g = _gate(client, token, tid, "click", {"label": "Confirmar baixa", "x": 408, "y": 365, "window": erp}, PNG)
    assert g["status"] == "waiting"
    req = open_request(client, env, tid)
    assert '"x": 408' in req["rationale"] and "Vai confirmar: fatura=88" in req["rationale"]
    client.post(f"/api/decisions/{req['id']}", headers=env["h"]["mgr"], json={"decision": "approve"})
    _hb(client, token)
    g = _gate(client, token, tid, "click", {"label": "Confirmar baixa", "x": 413, "y": 361, "window": erp}, PNG)
    assert g["status"] == "allowed" and g["where"] == {"x": 408, "y": 365}  # onde a pessoa aprovou
    _call(client, token, tid, "progress", {"desktop": {"event": g["event"], "after": "Confirmação"}})
    g = _gate(client, token, tid, "click", {"label": "Sim", "x": 130, "y": 125, "window": "Confirmação"}, PNG)
    assert g["status"] == "allowed" and g["covered_by"] == req["id"]  # o Sim do diálogo é parte da ação aprovada
    _call(client, token, tid, "progress", {"desktop": {"event": g["event"], "after": erp}})
    # a mesma baixa de novo, com os mesmos campos: recusada com a explicação (o modelo confere antes)
    _gate(client, token, tid, "type", {"text": "88", "label": "Fatura:", "window": erp})
    g = _gate(client, token, tid, "click", {"label": "Confirmar baixa", "x": 408, "y": 365, "window": erp}, PNG)
    assert g["status"] == "denied" and g["message"].startswith("NÃO CONFIRMEI")
    assert task(client, env, tid)["status"] == "in_progress"  # nada parou: o posto segue com a tarefa


def test_secret_goes_only_to_the_workstation_and_shadow_mode_simulates(client, env, rt):
    slug, token, tid = _worker(client, env, rt)
    client.put("/api/secrets", headers=ADMIN, json={"name": "erp-senha-local", "value": "s3nh4-local"})
    g = _gate(client, token, tid, "type", {"text": "secret://erp-senha-local", "label": "Senha", "window": "Login ERP"})
    assert g["status"] == "allowed" and g["text"] == "s3nh4-local" and g["secret"] is True
    t = task(client, env, tid)
    assert "s3nh4" not in str(t["events"])
    assert _desktop_events(client, env, tid)[-1]["value"] == "[segredo]"
    # ações desconhecidas e capturas inválidas: recusadas
    r = _call(client, token, tid, "gate", {"tool": "desktop:drag", "args": {}})
    assert r.status_code == 409
    r = _call(client, token, tid, "gate", {"tool": "desktop:screenshot", "args": {}, "screenshot": "não é base64!"})
    assert r.status_code == 409
    g = _gate(client, token, tid, "screenshot", {"window": "Login ERP"}, PNG)
    assert g["status"] == "allowed" and g["file"].startswith("tela-")
    # o evento de outro posto/tarefa não é alterado pelo progress
    other = _call(client, token, tid, "progress", {"desktop": {"event": 999999999, "after": "x"}})
    assert other.status_code == 200
    # modo sombra: o clique que confirma é simulado (não execute)
    with SessionLocal() as db:
        e = db.query(Employee).filter(Employee.worker_token_hash == _hash(token)).one()
        e.shadow = True
        db.commit()
    g = _gate(client, token, tid, "click", {"label": "Salvar", "x": 10, "y": 10, "window": "Login ERP"}, PNG)
    assert g["status"] in ("simulated", "waiting")


def test_platform_desktop_tools_are_off_for_an_external_employee(client, env, rt, monkeypatch):
    monkeypatch.setattr(desktop, "ready", lambda: True)
    slug, token, tid = _worker(client, env, rt)
    with SessionLocal() as db:
        e = db.query(Employee).filter(Employee.worker_token_hash == _hash(token)).one()
        e.desktop_apps = ["ERP Legado"]
        db.commit()
        assert desktop._avail(db, e) is False  # o desktop dele é o do posto (as ferramentas do app, com os mesmos nomes)
        e.runtime = "hangar"
        assert desktop._avail(db, e) is True
        db.rollback()
