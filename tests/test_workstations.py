# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Computadores compartilhados: a pessoa liga o computador pelo app, o funcionário (rodando na plataforma) pede
emprestado, a dona autoriza no próprio computador, os desktop_* de sempre passam a agir lá com a mesma alçada, o
segredo vai cifrado e só para a máquina, a fila anda quando o computador fica livre e Parar encerra o empréstimo."""
import json
import threading
import time

from app.db import SessionLocal
from app.models import WorkstationLease, WorkstationStep
from app.services import workstations

from .conftest import ADMIN
from .test_employees import assign, env, hire, make_active, open_request, rt, task, work  # noqa: F401
from .test_phase_g import _gate  # noqa: F401

PNG = "iVBORw0KGgo="


class FakeMachine(threading.Thread):
    """O app Agent Hangar Desktop de mentira: long-poll, executa os passos e devolve a tela."""

    def __init__(self, token: str):
        super().__init__(daemon=True)
        self.token, self.done, self.got, self.window = token, False, [], "ERP Legado 7.2"

    def run(self):
        while not self.done:
            try:
                with SessionLocal() as db:
                    out = workstations.heartbeat(db, self.token, {"os": "Windows 11"}, wait_s=0.3)
                    st = out.get("step")
                    if st:
                        self.got.append(st)
                        res = {"ok": True, "detail": f"{st['command']} feito", "window": self.window, "app": "ERP",
                               "size": [800, 600], "elements": ['[0] button "Confirmar baixa"'], "screenshot": PNG}
                        workstations.step_result(db, self.token, st["id"], res)
            except Exception:  # noqa: BLE001 — o computador desligado no fim do teste
                time.sleep(0.1)


def _register(client, headers, **over):
    body = {"name": "PC-ANA", "os": "Windows", "apps": [{"name": "ERP Legado", "process": "erp"}], **over}
    r = client.post("/api/app/workstations", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _hb(token, **info):
    with SessionLocal() as db:
        return workstations.heartbeat(db, token, info, 0)


def test_a_platform_employee_borrows_a_persons_computer(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    h = env["h"]
    # a pessoa liga o computador pelo app: o token aparece uma vez; sem app liberado, não liga
    assert client.post("/api/app/workstations", headers=h["own"], json={"name": "X", "apps": []}).status_code == 400
    ws = _register(client, h["own"])
    token = ws["token"]
    assert token.startswith("wst_") and ws["auth_mode"] == "ask" and ws["allow_managed"]
    assert "token" not in client.get("/api/app/workstations", headers=h["own"]).json()[0]
    other = _register(client, h["out"], name="PC-DE-FORA")  # de alguém que não tem relação com o funcionário
    tid = assign(client, env, slug, "dar baixa na fatura 88 no ERP do PC da Ana")
    listed = json.loads(_gate(slug, tid, "computer_list", {})["result"])
    names = [c["name"] for c in listed["computers"]]
    assert "PC-ANA" in names and "PC-DE-FORA" not in names
    assert not listed["computers"][names.index("PC-ANA")]["online"]
    # desligado (sem o app aberto): não dá para pedir
    assert "desligado" in _gate(slug, tid, "computer_use", {"computer": "PC-ANA", "reason": "baixa"})["result"]
    _hb(token)
    # pede: a dona tem de autorizar; a tarefa espera
    g = _gate(slug, tid, "computer_use", {"computer": "PC-ANA", "app": "ERP Legado", "reason": "dar baixa na fatura 88"})
    assert g["status"] == "waiting"
    assert task(client, env, tid)["status"] == "waiting_human"
    beat = _hb(token, seen_requests=0)
    assert [r["task_id"] for r in beat["requests"]] == [tid] and "baixa" in beat["requests"][0]["reason"]
    # o outro computador não vê o pedido
    assert _hb(other["token"])["requests"] == []
    # a dona permite no próprio computador
    with SessionLocal() as db:
        workstations.answer(db, token, beat["requests"][0]["lease_id"], True)
    t = task(client, env, tid)
    assert t["status"] == "new" and any(e["kind"] == "lease" and e["payload"]["action"] == "granted" for e in t["events"])
    machine = FakeMachine(token)
    machine.start()
    try:
        # os desktop_* de sempre agora agem no computador emprestado, com a tela de volta ao modelo
        g = _gate(slug, tid, "desktop_open", {"app": "ERP Legado"})
        assert g["status"] == "allowed" and g["images"] == [["image/png", PNG]]
        assert machine.got[-1]["command"] == "open" and machine.got[-1]["args"] == {"app": "ERP Legado"}
        # o segredo vai só para a máquina, marcado (ela só digita num campo de senha), e o passo não fica guardado
        client.put("/api/secrets", headers=ADMIN, json={"name": "erp-pc-ana", "value": "s3nh4-pc"})
        g = _gate(slug, tid, "desktop_type", {"text": "secret://erp-pc-ana", "label": "Senha", "x": 10, "y": 10})
        assert g["status"] == "allowed" and "s3nh4" not in g["result"]
        assert machine.got[-1]["args"] == {"text": "s3nh4-pc", "x": 10, "y": 10, "secret": True}
        with SessionLocal() as db:
            assert db.query(WorkstationStep).count() == 0
        assert all("s3nh4" not in json.dumps(e["payload"]) for e in task(client, env, tid)["events"])
        # o clique que confirma passa pela alçada do funcionário, como no desktop da plataforma
        g = _gate(slug, tid, "desktop_click", {"label": "Confirmar baixa", "x": 408, "y": 365})
        assert g["status"] == "waiting"
        req = open_request(client, env, tid)
        assert "Tela: tela-" in req["rationale"]
        client.post(f"/api/decisions/{req['id']}", headers=h["mgr"], json={"decision": "approve"})
        g = _gate(slug, tid, "desktop_click", {"label": "Confirmar baixa", "x": 410, "y": 360})
        assert g["status"] == "allowed" and machine.got[-1]["command"] == "click"
        assert (machine.got[-1]["args"]["x"], machine.got[-1]["args"]["y"]) == (408, 365)  # onde a pessoa aprovou

        # a fila: outra tarefa pede o mesmo computador (pré-autorizado agora) enquanto ele está em uso
        assert client.patch(f"/api/app/workstations/{ws['id']}", headers=h["own"],
                            json={"auth_mode": "preauthorized"}).json()["auth_mode"] == "preauthorized"
        tid2 = assign(client, env, slug, "outra baixa no ERP do PC da Ana")
        g = _gate(slug, tid2, "computer_use", {"computer": "PC-ANA", "reason": "outra baixa"})
        assert g["status"] == "waiting" and "fila" in g["message"]
        assert task(client, env, tid2)["status"] == "waiting_human"
        # a primeira devolve: a segunda passa a usar e continua sozinha
        assert "devolvido" in _gate(slug, tid, "computer_release", {})["result"]
        assert task(client, env, tid2)["status"] == "new"
        with SessionLocal() as db:
            lease2 = db.query(WorkstationLease).filter_by(task_id=tid2).one()
            assert lease2.status == "active"
        # a primeira tarefa não cai, calada, no desktop da plataforma
        assert "não está com o computador" in _gate(slug, tid, "desktop_look", {})["result"]
        assert _gate(slug, tid2, "desktop_look", {})["status"] == "allowed"
        # Parar no computador: o empréstimo acaba na hora
        with SessionLocal() as db:
            workstations.stop(db, token, lease2.id)
        assert "parou no computador" in _gate(slug, tid2, "desktop_look", {})["result"]
    finally:
        machine.done = True
        machine.join(timeout=3)
    # a dona desliga: o token deixa de valer
    assert client.delete(f"/api/app/workstations/{ws['id']}", headers=h["own"]).json()["status"] == "off"
    r = client.post("/hooks/workstation/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={})
    assert r.status_code == 401


def test_the_owner_can_refuse_and_only_she_decides(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    h = env["h"]
    ws = _register(client, h["own"], name="PC-RECUSA")
    _hb(ws["token"])
    tid = assign(client, env, slug, "usar o ERP")
    g = _gate(slug, tid, "computer_use", {"computer": "PC-RECUSA", "reason": "teste"})
    rid = g["request_id"]
    # o gestor do funcionário não decide o empréstimo do computador de outra pessoa
    r = client.post(f"/api/decisions/{rid}", headers=h["mgr"], json={"decision": "approve"})
    assert r.status_code in (400, 403, 409) and "dona" in r.text
    r = client.post(f"/api/decisions/{rid}", headers=h["own"], json={"decision": "reject", "reason": "agora não"})
    assert r.status_code == 200, r.text
    t = task(client, env, tid)
    assert t["status"] == "new"
    with SessionLocal() as db:
        assert db.query(WorkstationLease).filter_by(task_id=tid).one().status == "denied"
    # o app liga o computador pelo hook com o token dele, e um token qualquer não entra
    r = client.post("/hooks/workstation/heartbeat", headers={"Authorization": f"Bearer {ws['token']}"}, json={"wait_s": 0})
    assert r.status_code == 200 and r.json()["workstation"]["online"]
    assert client.post("/hooks/workstation/heartbeat", headers={"Authorization": "Bearer wst_nope"}, json={}).status_code == 401
