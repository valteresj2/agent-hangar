"""Galeria de templates: agentes prontos (YAML em /templates) aplicados via apply_document."""
import copy
import os

import yaml
from sqlalchemy.orm import Session

from .. import config
from .catalog import HARNESS_PROTOCOL, get_connection
from .common import PlatformError
from .registry import apply_document


def _load_all() -> dict[str, dict]:
    out = {}
    if not os.path.isdir(config.TEMPLATES_DIR):
        return out
    for fn in sorted(os.listdir(config.TEMPLATES_DIR)):
        if fn.endswith((".yaml", ".yml")):
            with open(os.path.join(config.TEMPLATES_DIR, fn), encoding="utf-8") as f:
                t = yaml.safe_load(f)
            out[t["id"]] = t
    return out


def list_templates() -> list[dict]:
    items = []
    for t in _load_all().values():
        agents = t.get("document", {}).get("agents", [])
        harness_ids = [((a.get("spec") or {}).get("harness") or {}).get("id") for a in agents]
        items.append({"id": t["id"], "title": t.get("title", t["id"]), "description": t.get("description", ""),
                      "tags": t.get("tags", []), "needs": t.get("needs", ""),
                      "agents": [a["name"] for a in agents],
                      "harness": next((h for h in harness_ids if h), None)})
    return items


def get_template(template_id: str) -> dict:
    t = _load_all().get(template_id)
    if not t:
        raise PlatformError(f"template '{template_id}' não existe")
    return t


def apply_template(db: Session, template_id: str, connection: str = "", harness_connection: str = "",
                   actor="admin") -> list[dict]:
    """Aplica o template. `connection` preenche o LLM dos agentes de chat; `harness_connection` o dos
    agentes-com-harness (se o protocolo bater). Sem conexões, os agentes nascem em modo mock."""
    doc = copy.deepcopy(get_template(template_id)["document"])
    if connection and get_connection(db, connection).protocol != "openai":
        raise PlatformError(f"'{connection}' não é uma conexão protocol='openai' (necessária para agente de chat)")
    for a in doc.get("agents", []):
        spec = a.setdefault("spec", {})
        h = spec.get("harness")
        if h and harness_connection:
            wanted = HARNESS_PROTOCOL[h["id"]]
            got = get_connection(db, harness_connection).protocol
            if got != wanted:
                raise PlatformError(f"o harness '{h['id']}' precisa de conexão protocol='{wanted}' "
                                    f"('{harness_connection}' é {got})")
            h["connection"] = harness_connection
        elif not h and connection:
            spec.setdefault("llm", {})
            if not spec["llm"].get("connection"):
                spec["llm"]["connection"] = connection
    return apply_document(db, doc, actor)
