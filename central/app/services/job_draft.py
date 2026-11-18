"""Rascunho do cargo de um Digital employee a partir de um texto livre ("toda manhã organize a minha caixa de e-mail e
rascunhe respostas; nunca envie sem eu aprovar"). Só preenche a ficha da tela de contratação: não cria nada, e a pessoa
revisa cada campo antes de contratar.

Com uma conexão de chat da empresa (protocolo openai), o modelo escreve o rascunho. Sem conexão, ou se a chamada falhar,
regras simples aproveitam o que dá do texto e a resposta diz isso (source="rules"), para a tela avisar o que falta."""
import re

import httpx
from sqlalchemy.orm import Session

from .. import crypto
from . import llm
from .access import Access, Forbidden
from .common import PlatformError

MAX_TEXT = 4000
SYSTEM = """You draft the job sheet of a Digital employee (an AI agent with a job title and a human manager) from what
a person asked for. Answer in the SAME language as the request, with one JSON object and nothing else:
{"name": "a short first name for the agent",
 "title": "job title, 2 to 5 words",
 "mission": "one sentence: the result it answers for",
 "responsibilities": ["3 to 6 short lines, each starting with a verb"],
 "systems": ["apps and systems named or clearly implied in the request, by their product name"],
 "probation_tasks": [{"title": "a real request someone would make to it", "expected": "what a good result looks like"}]}
Write exactly 3 probation_tasks. Use only what the request says or clearly implies; do not invent companies, people,
numbers or tools. Rules the person stated (for example "never send without my approval") go in responsibilities."""

# apps que as pessoas costumam citar pelo nome: sem LLM, é o que dá para tirar do texto com segurança
APPS = ("Gmail", "Outlook", "Google Calendar", "Google Drive", "Google Sheets", "Google Docs", "Slack", "Teams", "WhatsApp",
        "HubSpot", "Salesforce", "Pipedrive", "RD Station", "Notion", "Jira", "Trello", "Asana", "Linear", "GitHub", "GitLab",
        "Zendesk", "Intercom", "Freshdesk", "SAP", "Totvs", "Omie", "Conta Azul", "QuickBooks", "Stripe", "BigQuery",
        "Databricks", "Snowflake", "Postgres", "Excel", "SharePoint", "Confluence", "Figma", "Shopify", "CRM", "ERP")


def _target(db: Session):
    """(base_url, chave, modelo) da conexão de chat da empresa, ou None."""
    from .catalog import default_chat_llm, get_connection
    d = default_chat_llm(db)
    if not d:
        return None
    conn = get_connection(db, d["connection"])
    model = d.get("model") or conn.model_name
    if not model or str(model).startswith("mock"):
        return None
    return conn.base_url, crypto.decrypt(conn.api_key), model


def _str(v, limit: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _lines(v, limit: int, most: int) -> list[str]:
    out = []
    for x in v if isinstance(v, list) else []:
        s = _str(x, limit)
        if s and s not in out:
            out.append(s)
    return out[:most]


def _clean(d: dict) -> dict:
    """Só os campos da ficha, com tamanho limitado: o que o modelo devolveu é dado, não é confiável."""
    tasks = []
    for t in d.get("probation_tasks") if isinstance(d.get("probation_tasks"), list) else []:
        if isinstance(t, dict) and _str(t.get("title"), 200):
            tasks.append({"title": _str(t.get("title"), 200), "body": _str(t.get("title"), 200),
                          "expected": _str(t.get("expected"), 300)})
    return {"name": _str(d.get("name"), 40), "title": _str(d.get("title"), 80), "mission": _str(d.get("mission"), 400),
            "responsibilities": _lines(d.get("responsibilities"), 200, 8), "systems": _lines(d.get("systems"), 60, 12),
            "probation_tasks": tasks[:3]}


def _rules(text: str) -> dict:
    """Sem modelo: a missão é a primeira frase, as responsabilidades são as frases do pedido e os sistemas são os apps
    citados pelo nome. O cargo e os pedidos de teste ficam para a pessoa."""
    parts = [p.strip(" -•\t") for p in re.split(r"(?<=[.!?;])\s+|\n+", text) if p.strip(" -•\t")]
    low = text.lower()
    systems = [a for a in APPS if re.search(rf"(?<![\w]){re.escape(a.lower())}(?![\w])", low)]
    return _clean({"mission": parts[0] if parts else "", "responsibilities": parts if len(parts) >= 3 else [],
                   "systems": systems})


def draft(db: Session, acc: Access, text: str) -> dict:
    if not acc.p.user_id and not acc.p.is_admin:
        raise Forbidden("entre com a sua conta para rascunhar um cargo")
    text = (text or "").strip()[:MAX_TEXT]
    if len(text) < 10:
        raise PlatformError("descreva em uma ou duas frases o que ele deve fazer")
    try:
        got = llm.complete_json(_target(db), SYSTEM, text)
    except (httpx.HTTPError, PlatformError, ValueError, KeyError):
        got = None  # o modelo falhou: a ficha ainda sai, pelas regras
    if isinstance(got, dict):
        fields = _clean(got)
        if fields["title"] or fields["mission"]:
            return {"source": "llm", "fields": fields}
    return {"source": "rules", "fields": _rules(text)}
