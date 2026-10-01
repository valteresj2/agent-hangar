"""Avaliação de código em stage: spec do workspace, veredito (check + arquivos protegidos), token de uso único do
sandbox e o proxy interno para o stage do agente."""
import threading

import httpx
import pytest

from app import services as svc
from app.db import SessionLocal
from app.spec import SpecError, validate

from .conftest import ADMIN

WS = {"files": {"calc.py": "def soma(a, b):\n    return a - b\n",
                "test_calc.py": "import unittest\nfrom calc import soma\n\nclass T(unittest.TestCase):\n"
                                "    def test(self):\n        self.assertEqual(soma(2, 3), 5)\n"},
      "check": "python3 -m unittest", "protected": ["test_calc.py"]}


def test_workspace_spec_validation():
    ok = validate({"tests": [{"name": "bug", "input": "corrija", "workspace": WS}]})
    assert ok["tests"][0]["workspace"]["max_rounds"] == 30
    for bad in ({"files": {"../x.py": "1"}, "check": "true"}, {"files": {"/etc/x": "1"}, "check": "true"},
                {"files": {}, "check": "true"}, {"files": {"a.py": "x" * 200_001}, "check": "true"}):
        with pytest.raises(SpecError):
            validate({"tests": [{"input": "x", "workspace": bad}]})


def test_verdict():
    base = {"rounds": 5, "tool_calls": ["read_file(calc.py)", "write_file(calc.py)", "run_command(python3 -m unittest)"],
            "changed_files": ["calc.py"], "protected_changed": [], "check_output": "Ran 1 test\n\nOK"}
    ok, detail = svc.code_eval.verdict({**base, "check_exit": 0}, WS)
    assert ok and "exit 0" in detail and "alterou: calc.py" in detail
    ok, detail = svc.code_eval.verdict({**base, "check_exit": 1}, WS)
    assert not ok and "exit 1" in detail
    ok, detail = svc.code_eval.verdict({**base, "check_exit": 0, "protected_changed": ["test_calc.py"]}, WS)
    assert not ok and "arquivo protegido" in detail  # passar mudando o teste não vale
    ok, detail = svc.code_eval.verdict({"error": "HTTP 502", "check_exit": None}, WS)
    assert not ok and "erro no sandbox" in detail


def test_run_with_simulated_sandbox_and_single_use_token(client):
    seen = {}

    def sandbox(env):
        token = env["EVAL_URL"].rsplit("/", 1)[1]
        seen["token"], seen["env"] = token, env

        def work():  # o runner real devolve o resultado por HTTP, de outro processo
            r = client.post(f"/internal/eval/{token}/result", json={
                "rounds": 3, "tool_calls": ["write_file(calc.py)"], "check_exit": 0, "check_output": "OK",
                "protected_changed": [], "changed_files": ["calc.py"]})
            assert r.status_code == 200
        threading.Thread(target=work).start()

    ok, detail = svc.code_eval.run("dev-bot", {"input": "corrija soma", "workspace": WS, "timeout_s": 20}, runner=sandbox)
    assert ok and "3 rodada(s)" in detail
    assert seen["env"]["EVAL_CHECK"] == "python3 -m unittest" and "test_calc.py" in seen["env"]["EVAL_PROTECTED"]
    # encerrada: o token não vale mais (nem para o proxy, nem para outro resultado)
    assert client.post(f"/internal/eval/{seen['token']}/result", json={}).status_code == 404
    assert client.post(f"/internal/eval/{seen['token']}/v1/chat/completions", json={"messages": []}).status_code == 404


def test_run_times_out(client):
    ok, detail = svc.code_eval.run("dev-bot", {"input": "x", "workspace": WS, "timeout_s": 1}, runner=lambda env: None)
    assert not ok and "tempo esgotado" in detail


def test_proxy_forwards_to_stage_of_the_evaluated_agent(client, monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
    monkeypatch.setattr(httpx, "post", fake_post)
    token = "t" * 32
    from app import shared
    shared.put(f"eval:{token}", {"slug": "dev-bot"}, 60)
    try:
        r = client.post(f"/internal/eval/{token}/v1/chat/completions", json={"messages": [{"role": "user", "content": "oi"}],
                                                                              "stream": True, "tools": []})
        assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "ok"
        url, kw = calls[0]
        assert url.endswith("agent-dev-bot-stage:8000/v1/chat/completions")
        assert kw["json"]["stream"] is False and kw["headers"]["X-Channel"] == "code-eval"
    finally:
        shared.pop(f"eval:{token}")


def test_run_tests_integration(client, uniq, monkeypatch):
    slug = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Coder"), "objective": "o", "final_output": "f"}).json()["slug"]
    client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"tests": [{"name": "bug soma", "input": "corrija", "workspace": WS}]})
    # sem conexão de LLM (mock): não executa o sandbox, avisa
    from app.services import testing
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        spec = svc.spec_of(a)
        ok, detail = testing._code_case(db, a, spec, spec["tests"][0])
        assert ok and "mock" in detail
        monkeypatch.setattr(testing, "is_mock", lambda spec, env="stage": False)
        calls = []
        monkeypatch.setattr(svc.code_eval, "run", lambda s, case: calls.append((s, case["name"])) or (True, "ok"))
        assert testing._code_case(db, a, spec, spec["tests"][0]) == (True, "ok") and calls == [(slug, "bug soma")]
        ok, detail = testing._code_case(db, a, {**spec, "llm": {"client_tools": False}}, spec["tests"][0])
        assert not ok and "client_tools" in detail
