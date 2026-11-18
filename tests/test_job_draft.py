"""Rascunho do cargo a partir de um texto livre: com modelo, a ficha vem dele (limpa e limitada); sem modelo ou com o
modelo falhando, regras simples aproveitam o texto e a resposta diz isso. Nunca cria nada."""
import httpx

from app.services import job_draft, llm

from .test_employees import env  # noqa: F401  (fixture)

ASK = ("Toda manhã de dia útil, organize a minha caixa do Gmail e rascunhe respostas. Às segundas, revise o pipeline do "
       "HubSpot. Nunca envie nada sem eu aprovar.")


def _draft(client, env, text=ASK):  # noqa: F811
    return client.post("/api/employees/draft", headers=env["h"]["req"], json={"text": text})


def test_without_a_model_the_rules_use_only_what_the_text_says(client, env):  # noqa: F811
    before = len(client.get("/api/employees", headers=env["h"]["req"]).json())
    r = _draft(client, env)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"] == "rules"
    f = d["fields"]
    assert f["title"] == "" and f["probation_tasks"] == [], "o que não está no texto fica para a pessoa"
    assert f["mission"].startswith("Toda manhã de dia útil") and len(f["responsibilities"]) == 3
    assert f["systems"] == ["Gmail", "HubSpot"]
    assert len(client.get("/api/employees", headers=env["h"]["req"]).json()) == before, "rascunhar não contrata"


def test_with_a_model_the_sheet_is_cleaned_and_limited(client, env, monkeypatch):  # noqa: F811
    seen = {}

    def fake(tgt, system, user):
        seen.update(tgt=tgt, user=user)
        return {"name": "Helena", "title": "Assistente  de e-mail", "mission": "Manter a caixa em dia.",
                "responsibilities": ["organizar a caixa", "rascunhar respostas", "", "nunca enviar sem aprovação"],
                "systems": ["Gmail", "Gmail", "HubSpot"], "status": "active", "manager": "outra@pessoa.com",
                "probation_tasks": [{"title": f"Pedido {i}", "expected": "x" * 900} for i in range(5)] + ["lixo"]}
    monkeypatch.setattr(job_draft, "_target", lambda db: ("http://llm.test", "k", "modelo"))
    monkeypatch.setattr(llm, "complete_json", fake)
    d = _draft(client, env).json()
    assert d["source"] == "llm" and seen["tgt"][2] == "modelo" and seen["user"] == ASK
    f = d["fields"]
    assert set(f) == {"name", "title", "mission", "responsibilities", "systems", "probation_tasks"}, "só os campos da ficha"
    assert f["title"] == "Assistente de e-mail" and f["systems"] == ["Gmail", "HubSpot"]
    assert f["responsibilities"] == ["organizar a caixa", "rascunhar respostas", "nunca enviar sem aprovação"]
    assert len(f["probation_tasks"]) == 3 and all(len(t["expected"]) == 300 for t in f["probation_tasks"])


def test_a_failing_model_falls_back_to_the_rules(client, env, monkeypatch):  # noqa: F811
    def boom(tgt, system, user):
        raise httpx.ConnectError("fora do ar")
    monkeypatch.setattr(job_draft, "_target", lambda db: ("http://llm.test", "k", "modelo"))
    monkeypatch.setattr(llm, "complete_json", boom)
    assert _draft(client, env).json()["source"] == "rules"
    monkeypatch.setattr(llm, "complete_json", lambda *a: {"title": "", "mission": ""})
    assert _draft(client, env).json()["source"] == "rules", "resposta vazia do modelo não vira ficha"


def test_needs_a_real_request_and_a_signed_in_person(client, env):  # noqa: F811
    assert _draft(client, env, "oi").status_code == 400
    assert client.post("/api/employees/draft", json={"text": ASK}).status_code == 401
