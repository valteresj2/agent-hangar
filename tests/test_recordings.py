# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Gravar uma tarefa: a gravação do app (passos, explicação, capturas) vira o rascunho do funcionário — pelas regras sem
LLM, ou pelo modelo com visão —, a pessoa revisa e contrata em modo sombra e experiência, com a rotina na agenda que
ela disse. E o computador bloqueado: a tarefa espera e avisa em vez de falhar."""
import base64
import json

from app.db import SessionLocal
from app.models import (
    Employee,
    EmployeeRoutine,
    EmployeeTask,
    HumanRequest,
    LlmConnection,
    LlmModel,
    Recording,
    WorkstationLease,
)
from app.services import recordings, workstations

from .test_employees import assign, env, hire, make_active, rt, task  # noqa: F401
from .test_phase_g import _gate  # noqa: F401

PNG = "iVBORw0KGgo="


def _package(**over):
    body = {
        "title": "Lançar as faturas da semana",
        "recorded_on": "Computador (PC-ANA)",
        "duration_s": 95,
        "apps": [{"name": "Mini ERP", "process": "MiniErp"}],
        "notes": "",
        "transcript": [{"start": 0, "end": 8, "text": "Toda segunda às 9h eu lanço as faturas vencidas no ERP."}],
        "steps": [
            {"t": 0, "kind": "window", "app": "Mini ERP", "window": "Mini ERP 1.0", "text": "abriu a janela"},
            {"t": 1200, "kind": "click", "app": "Mini ERP", "element": {"name": "Fatura", "type": "edit"}, "frame": 0},
            {"t": 3000, "kind": "type", "app": "Mini ERP", "field": "Fatura", "value": "1234"},
            {"t": 4000, "kind": "type", "app": "Mini ERP", "field": "Senha", "password": True, "value": "vazou?"},
            {"t": 5000, "kind": "click", "outside": True},
            {"t": 6000, "kind": "click", "app": "Mini ERP", "element": {"name": "Lançar", "type": "button"}, "frame": 1},
        ],
        "frames": [{"frame": 0, "step": 1, "png": PNG}, {"frame": 1, "step": 5, "png": PNG}],
    }
    body.update(over)
    return body


def _drop_tasks(employee_id: int):
    """The test DB is shared: tasks left "new" would take the queue's slots of the next tests' probation."""
    with SessionLocal() as db:
        for t in db.query(EmployeeTask).filter(EmployeeTask.employee_id == employee_id,
                                                 EmployeeTask.status.notin_(("done", "failed", "cancelled"))):
            t.status = "cancelled"
        db.commit()


def _no_llm(monkeypatch):
    monkeypatch.setattr(recordings, "draft_target", lambda db: (None, False))


# ------------------------------------------------------------------ regras (sem LLM)
def test_schedule_is_read_from_what_the_person_said():
    s = recordings.schedule_of
    assert s("toda segunda às 9h eu lanço")["cron"] == "0 9 * * 1"
    assert s("todo dia útil às 8:30")["cron"] == "30 8 * * 1-5"
    assert s("todo dia 5 às 10h fecho o mês")["cron"] == "0 10 5 * *"
    assert s("diariamente às 18h")["cron"] == "0 18 * * *"
    assert s("toda sexta")["cron"] == "0 9 * * 5" and "confirme" in s("toda sexta")["text"]
    assert s("eu faço isso de vez em quando")["cron"] == ""


def test_a_recording_becomes_a_draft_by_the_rules_without_llm(client, env, monkeypatch):
    _no_llm(monkeypatch)
    h = env["h"]
    r = client.post("/api/app/recordings", headers=h["own"], json=_package())
    assert r.status_code == 200, r.text
    rec = r.json()
    d = rec["draft"]
    assert rec["status"] == "drafted" and rec["model"] == "regras"
    assert d["schedule"]["cron"] == "0 9 * * 1"
    # a senha nunca vira valor: vira um nome do cofre; o "Lançar" confirma algo
    assert d["secrets"] == [{"name": "mini-erp-senha", "field": "Senha"}]
    assert any(s.get("value") == "secret://mini-erp-senha" for s in d["steps"])
    assert any(s["confirms"] for s in d["steps"] if "Lançar" in s["target"])
    assert len(d["probation"]) == 3 and all(p["expected"] for p in d["probation"])
    # o que muda a cada vez vira pergunta (de onde vem a fatura?)
    assert any("Fatura" in q["question"] for q in d["questions"])
    # nada das capturas nem da senha fica guardado
    with SessionLocal() as db:
        row = db.get(Recording, rec["id"])
        raw = json.dumps(row.package)
        assert "vazou" not in raw and PNG not in raw and "frames" not in row.package
    # só a dona vê e mexe na gravação
    assert client.get(f"/api/app/recordings/{rec['id']}", headers=h["out"]).status_code == 400
    assert [x["id"] for x in client.get("/api/app/recordings", headers=h["own"]).json()][0] == rec["id"]


def test_an_empty_or_unexplained_recording_is_refused(client, env, monkeypatch):
    _no_llm(monkeypatch)
    h = env["h"]
    only_outside = _package(steps=[{"t": 0, "kind": "click", "outside": True}])
    assert "nenhum passo" in client.post("/api/app/recordings", headers=h["own"], json=only_outside).text
    unexplained = _package(transcript=[], notes="")
    assert "explique" in client.post("/api/app/recordings", headers=h["own"], json=unexplained).text


def test_the_vision_model_sees_the_captures(client, env, monkeypatch):
    seen = {}

    def fake_parts(base, key, model, system, parts):
        seen["images"] = [p for p in parts if p["type"] == "image_url"]
        seen["model"] = model
        return json.dumps({"title": "Lançador de faturas", "mission": "Lançar as faturas vencidas toda segunda.",
                           "steps": [{"app": "Mini ERP", "action": "click", "target": 'button "Lançar"', "confirms": True}],
                           "schedule": {"cron": "0 9 * * 1", "text": "toda segunda às 9h"},
                           "questions": [{"question": "E se não houver fatura vencida?", "answer": ""}]})
    monkeypatch.setattr(recordings, "draft_target", lambda db: (("http://llm.test/v1", "", "vision-x"), True))
    monkeypatch.setattr(recordings, "CALL_PARTS", fake_parts)
    rec = client.post("/api/app/recordings", headers=env["h"]["own"], json=_package()).json()
    assert rec["status"] == "drafted" and rec["model"] == "vision-x"
    assert len(seen["images"]) == 2 and seen["images"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    d = rec["draft"]
    assert d["title"] == "Lançador de faturas" and d["steps"][0]["confirms"] is True
    # o que o modelo não trouxe, as regras completam (ensaios mínimos, senhas)
    assert len(d["probation"]) >= 3 and d["secrets"]


def test_transcription_needs_a_speech_model_and_does_not_keep_the_audio(client, env, monkeypatch):
    h = env["h"]
    audio = base64.b64encode(b"webm-bytes").decode()
    monkeypatch.setattr(recordings, "stt_target", lambda db: None)
    r = client.post("/api/app/recordings/transcribe", headers=h["own"], json={"audio": audio, "mime": "audio/webm"})
    assert r.status_code == 400 and "modelo de fala" in r.text
    got = {}

    def fake(base, key, model, data, mime):
        got.update(model=model, size=len(data), mime=mime)
        return {"text": "toda segunda às 9h", "segments": [{"start": 0, "end": 2.5, "text": "toda segunda às 9h"}]}
    monkeypatch.setattr(recordings, "stt_target", lambda db: ("http://llm.test/v1", "", "whisper-1"))
    monkeypatch.setattr(recordings, "TRANSCRIBE", fake)
    r = client.post("/api/app/recordings/transcribe", headers=h["own"], json={"audio": audio, "mime": "audio/webm"})
    assert r.status_code == 200, r.text
    assert r.json()["segments"][0]["text"] == "toda segunda às 9h" and got == {"model": "whisper-1", "size": 10,
                                                                               "mime": "audio/webm"}


def test_stt_target_comes_from_the_catalog(client, uniq):
    with SessionLocal() as db:
        c = LlmConnection(name=uniq("stt-conn"), base_url="http://llm.test/v1", model_name="gpt-x", api_key="")
        db.add(c)
        db.flush()
        db.add(LlmModel(connection_id=c.id, model_id="whisper-large", kind="stt", caps=[]))
        db.commit()
        tgt = recordings.stt_target(db)
        assert tgt is not None and tgt[2] in {m.model_id for m in db.query(LlmModel).filter_by(kind="stt")}


# ------------------------------------------------------------------ contratar
def test_hiring_from_the_reviewed_draft_starts_shadow_and_probation(client, env, rt, monkeypatch):
    _no_llm(monkeypatch)
    h = env["h"]
    ws = client.post("/api/app/workstations", headers=h["own"],
                     json={"name": "PC-GRAVA", "apps": [{"name": "Mini ERP", "process": "MiniErp"}]}).json()
    rec = client.post("/api/app/recordings", headers=h["own"], json=_package()).json()
    d = rec["draft"]
    # com pergunta sem resposta, não contrata
    r = client.post(f"/api/app/recordings/{rec['id']}/hire", headers=h["own"], json={"draft": d, "workstation_id": ws["id"]})
    assert r.status_code == 400 and "perguntas" in r.text
    for q in d["questions"]:
        q["answer"] = "da planilha de vencidas"
    assert client.put(f"/api/app/recordings/{rec['id']}/draft", headers=h["own"], json={"draft": d}).status_code == 200
    # o computador tem de ser da própria pessoa
    other = client.post("/api/app/workstations", headers=h["out"],
                        json={"name": "PC-OUTRO", "apps": [{"name": "Mini ERP", "process": "MiniErp"}]}).json()
    r = client.post(f"/api/app/recordings/{rec['id']}/hire", headers=h["own"], json={"draft": d, "workstation_id": other["id"]})
    assert r.status_code == 400 and "não é seu" in r.text
    r = client.post(f"/api/app/recordings/{rec['id']}/hire", headers=h["own"], json={"draft": d, "workstation_id": ws["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "hired" and out["probation_started"] is True
    slug = out["employee"]["slug"]
    with SessionLocal() as db:
        e = db.get(Employee, out["employee_id"])
        assert e.shadow is True and e.autonomy_level == "intern" and e.status == "probation"
        routine = db.query(EmployeeRoutine).filter_by(employee_id=e.id).one()
        assert routine.cron.startswith("0 9 * * 1") and "PC-GRAVA" in routine.body and "secret://mini-erp-senha" in routine.body
        probation = db.query(EmployeeTask).filter_by(employee_id=e.id, probation=True).all()
        assert len(probation) == 3 and all("computer_use" in t.body for t in probation)
        # each rehearsal carries the values of the recording, so it does not have to ask for them
        assert all("Dados para este ensaio" in t.body and "1234" in t.body for t in probation)
    assert slug
    # não contrata duas vezes
    r = client.post(f"/api/app/recordings/{rec['id']}/hire", headers=h["own"], json={"draft": d})
    assert r.status_code == 400 and "já virou" in r.text
    _drop_tasks(out["employee_id"])


# ------------------------------------------------------------------ computador bloqueado
def test_a_locked_computer_makes_the_task_wait_and_continue(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    h = env["h"]
    ws = client.post("/api/app/workstations", headers=h["own"],
                     json={"name": "PC-BLOQ", "apps": [{"name": "ERP Legado", "process": "erp"}]}).json()
    token = ws["token"]
    with SessionLocal() as db:
        workstations.heartbeat(db, token, {"locked": True}, 0)
    tid = assign(client, env, slug, "dar baixa no ERP do PC bloqueado")
    g = _gate(slug, tid, "computer_use", {"computer": "PC-BLOQ", "reason": "baixa"})
    assert g["status"] == "waiting" and "bloqueado" in g["message"] and "2 h" in g["message"]
    assert task(client, env, tid)["status"] == "waiting_human"
    with SessionLocal() as db:
        lease = db.query(WorkstationLease).filter_by(task_id=tid).one()
        assert lease.status == "waiting"
        r = db.get(HumanRequest, lease.request_id)
        assert r.kind == "workstation_wait" and r.assigned_user_id is not None  # a dona é avisada
    # pedir de novo enquanto espera não cria outro empréstimo
    assert _gate(slug, tid, "computer_use", {"computer": "PC-BLOQ"})["status"] == "waiting"
    with SessionLocal() as db:
        assert db.query(WorkstationLease).filter_by(task_id=tid).count() == 1
        # a pessoa desbloqueia: o pedido de autorização (ask) aparece no computador dela
        beat = workstations.heartbeat(db, token, {"locked": False}, 0)
        assert [x["task_id"] for x in beat["requests"]] == [tid]
        lease = db.query(WorkstationLease).filter_by(task_id=tid).one()
        assert lease.status == "requested"
        workstations.answer(db, token, lease.id, True)
    assert task(client, env, tid)["status"] == "new"
    with SessionLocal() as db:
        _drop_tasks(db.get(EmployeeTask, tid).employee_id)


def test_a_computer_never_seen_is_still_an_error(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    client.post("/api/app/workstations", headers=env["h"]["own"],
                json={"name": "PC-NOVO", "apps": [{"name": "ERP Legado", "process": "erp"}]})
    tid = assign(client, env, slug, "usar o ERP")
    assert "desligado" in _gate(slug, tid, "computer_use", {"computer": "PC-NOVO", "reason": "x"})["result"]
