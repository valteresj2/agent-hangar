"""Plugins (P1): conectar qualquer sistema à plataforma com um pacote declarativo, sem código rodando na central.

Um plugin é um manifesto (hangar-plugin.yaml) com pontos de extensão fechados:
- `base_url` + `auth`: o único host com que ele fala e como se autentica (api_key, bearer, basic ou nenhuma);
- `tools`: operações HTTP (método, caminho, parâmetros em JSON Schema), cada uma com o tipo de ação para a alçada;
- `settings`: configurações pedidas na instalação (as `secret` são criptografadas), usáveis como {{settings.x}};
- `skills`: conhecimento que os agentes que usam o plugin recebem.

Ciclo de vida: rascunho -> enviado -> aprovado por OUTRA pessoa (admin) -> instalável. Editar cria um rascunho novo; as
instalações seguem na versão aprovada. Instalação por time (mantenedor) ou para a empresa (admin), com a credencial
do time. Um agente usa com `plugins: [nome]` na spec: a central serve o plugin como um servidor MCP interno
(/internal/plugins/<nome>/mcp), injeta a credencial e chama o sistema — o segredo nunca entra no container do agente,
e cada ferramenta passa pela alçada como mcp:plugin-<nome>:<ferramenta>, já classificada pelo manifesto.
"""
import base64
import copy
import ipaddress
import json
import re
import socket
import urllib.parse
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from .. import config, crypto
from ..models import ActionCatalog, Agent, Plugin, PluginInstall, Team, now
from . import employee_gate as gatemod
from .access import RANK, Access, Forbidden, find_team
from .common import PlatformError, audit, iso

STATUSES = ("draft", "pending", "approved", "rejected", "disabled")
MAX_TOOLS = 50
MAX_OUTPUT = 8000
HTTP = lambda: httpx.Client(timeout=config.PLUGIN_TIMEOUT_S, follow_redirects=False)  # noqa: E731  (os testes trocam)
_TPL = re.compile(r"\{\{\s*settings\.([a-zA-Z0-9_]+)\s*\}\}")
_PATH_PARAM = re.compile(r"\{([a-zA-Z0-9_]+)\}")


# ------------------------------------------------------------------ manifesto
class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PluginAuth(_M):
    type: Literal["none", "api_key", "bearer", "basic"] = "none"
    in_: Literal["header", "query"] = Field(default="header", alias="in")
    name: str = Field(default="", description="header ou parâmetro da chave (api_key); padrão X-API-Key")
    label: str = Field(default="", description="como a credencial aparece na instalação")


class PluginSetting(_M):
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,40}$")
    title: str = ""
    description: str = ""
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = False
    secret: bool = False
    default: str | float | bool | None = None


class PluginTool(_M):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    description: str = ""
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str
    action: str = ""
    risk: int | None = Field(default=None, ge=1, le=5)
    reversible: bool = False
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _path(cls, v):
        if not v.startswith("/") or "://" in v or ".." in v.split("?")[0].split("/") or "\\" in v:
            raise ValueError("path começa com / e fica no host do plugin (sem esquema, sem ..)")
        return v

    @model_validator(mode="after")
    def _action(self):
        if not self.action:
            self.action = "read" if self.method == "GET" else ("delete" if self.method == "DELETE" else "write_internal")
        if self.action not in gatemod.ACTION_TYPES:
            raise ValueError(f"action '{self.action}': use {', '.join(gatemod.ACTION_TYPES)}")
        if self.parameters.get("type", "object") != "object":
            raise ValueError("parameters precisa ser um JSON Schema de objeto")
        return self


class PluginSkill(_M):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,60}$")
    description: str = ""
    content: str = Field(max_length=20000)


class PluginTest(_M):
    tool: str
    args: dict = Field(default_factory=dict)


class PluginManifest(_M):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    title: str = ""
    version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$")
    description: str = ""
    publisher: str = ""
    base_url: str
    auth: PluginAuth = Field(default_factory=PluginAuth)
    settings: list[PluginSetting] = Field(default_factory=list)
    tools: list[PluginTool] = Field(min_length=1, max_length=MAX_TOOLS)
    skills: list[PluginSkill] = Field(default_factory=list)
    test: PluginTest | None = None

    @field_validator("base_url")
    @classmethod
    def _base(cls, v):
        u = urllib.parse.urlparse(_TPL.sub("x", v))
        if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password:
            raise ValueError("base_url: uma URL http(s) sem usuário e senha")
        return v.rstrip("/")

    @model_validator(mode="after")
    def _refs(self):
        names = [t.name for t in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("nomes de ferramentas repetidos")
        keys = {s.key for s in self.settings}
        used = set(_TPL.findall(self.base_url))
        for t in self.tools:
            used |= set(_TPL.findall(t.path)) | {k for h in t.headers.values() for k in _TPL.findall(h)}
        if used - keys:
            raise ValueError(f"settings usadas e não declaradas: {', '.join(sorted(used - keys))}")
        if self.test and self.test.tool not in names:
            raise ValueError(f"test.tool '{self.test.tool}' não é uma ferramenta do plugin")
        if self.auth.type == "api_key" and not self.auth.name:
            self.auth.name = "X-API-Key"
        return self


def parse(manifest) -> dict:
    """Aceita dict, JSON ou YAML; devolve o manifesto validado e normalizado."""
    if isinstance(manifest, str):
        try:
            manifest = yaml.safe_load(manifest)
        except yaml.YAMLError as e:
            raise PlatformError(f"manifesto inválido (YAML): {e}") from None
    if not isinstance(manifest, dict):
        raise PlatformError("o manifesto precisa ser um objeto (YAML ou JSON)")
    try:
        return PluginManifest.model_validate(manifest).model_dump(by_alias=True, exclude_none=True)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:8])
        raise PlatformError(f"manifesto inválido — {msgs}") from None


def permissions(m: dict) -> dict:
    """O que o plugin pode fazer, para a tela de revisão e de instalação."""
    host = urllib.parse.urlparse(_TPL.sub("{setting}", m["base_url"])).hostname or ""
    actions: dict[str, int] = {}
    for t in m["tools"]:
        actions[t["action"]] = actions.get(t["action"], 0) + 1
    return {"host": host, "templated_host": bool(_TPL.search(m["base_url"])), "auth": m["auth"]["type"],
            "actions": actions, "tools": len(m["tools"]), "skills": len(m.get("skills") or []),
            "secrets": [s["key"] for s in m.get("settings") or [] if s.get("secret")],
            "risky": sorted({t["action"] for t in m["tools"] if gatemod.RISK.get(t["action"], 3) >= 4})}


# ------------------------------------------------------------------ importar de um OpenAPI
def _snake(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s or "")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return (s if s and s[0].isalpha() else f"op_{s}")[:60]


def _deref(doc: dict, node, depth: int = 0):
    if depth > 8:
        return {}
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str) and node["$ref"].startswith("#/"):
            cur = doc
            for part in node["$ref"][2:].split("/"):
                cur = cur.get(part, {}) if isinstance(cur, dict) else {}
            return _deref(doc, cur, depth + 1)
        return {k: _deref(doc, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_deref(doc, v, depth + 1) for v in node]
    return node


def from_openapi(document, name: str = "", base_url: str = "", only: list[str] | None = None) -> dict:
    """Rascunho de manifesto a partir de um OpenAPI 3 (JSON ou YAML). As ações vêm de um palpite pelo método e pelo
    nome da operação: revise antes de enviar."""
    doc = yaml.safe_load(document) if isinstance(document, str) else document
    if not isinstance(doc, dict) or not str(doc.get("openapi", "")).startswith("3"):
        raise PlatformError("mande um documento OpenAPI 3 (JSON ou YAML)")
    info = doc.get("info") or {}
    base = base_url or next((s.get("url", "") for s in doc.get("servers") or [] if s.get("url", "").startswith("http")), "")
    if not base:
        raise PlatformError("o OpenAPI não traz servers[].url absoluto: informe base_url")
    tools = []
    for path, ops in (doc.get("paths") or {}).items():
        common = (ops or {}).get("parameters") or []
        for method, op in (ops or {}).items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE") or not isinstance(op, dict):
                continue
            tname = _snake(op.get("operationId") or f"{method}_{path}")
            if only and tname not in only:
                continue
            props, req = {}, []
            for p in _deref(doc, [*common, *(op.get("parameters") or [])]):
                if p.get("in") in ("path", "query") and p.get("name"):
                    sch = dict(p.get("schema") or {"type": "string"})
                    if p.get("description"):
                        sch["description"] = p["description"][:300]
                    props[p["name"]] = sch
                    if p.get("required") or p.get("in") == "path":
                        req.append(p["name"])
            body = _deref(doc, ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema"))
            if isinstance(body, dict) and body.get("type", "object") == "object":
                props.update(body.get("properties") or {})
                req += [r for r in body.get("required") or [] if r not in req]
            m = method.upper()
            action = ("read" if m == "GET" else "delete" if m == "DELETE" else
                      gatemod._by_name(tname, read=False))
            schema = {"type": "object", "properties": props, **({"required": req} if req else {})}
            tools.append({"name": tname, "description": (op.get("summary") or op.get("description") or "")[:500],
                          "method": m, "path": path, "action": action, "parameters": schema})
            if len(tools) >= MAX_TOOLS:
                break
    if not tools:
        raise PlatformError("nenhuma operação encontrada no OpenAPI")
    auth = {"type": "none"}
    for sch in ((doc.get("components") or {}).get("securitySchemes") or {}).values():
        if sch.get("type") == "apiKey" and sch.get("in") in ("header", "query"):
            auth = {"type": "api_key", "in": sch["in"], "name": sch.get("name", "X-API-Key")}
            break
        if sch.get("type") == "http" and sch.get("scheme", "").lower() in ("bearer", "basic"):
            auth = {"type": sch["scheme"].lower()}
            break
    slug = re.sub(r"[^a-z0-9-]+", "-", (name or info.get("title") or "plugin").lower()).strip("-")[:40] or "plugin"
    if not slug[0].isalpha():
        slug = f"p-{slug}"[:40]
    version = str(info.get("version") or "0.1.0")
    return parse({"name": slug, "title": info.get("title") or slug, "description": (info.get("description") or "")[:2000],
                  "version": version if re.match(r"^\d+\.\d+\.\d+", version) else "0.1.0", "base_url": base,
                  "auth": auth, "tools": tools})


# ------------------------------------------------------------------ permissões e visão
def live(p: Plugin) -> bool:
    """Tem uma versão aprovada em uso (mesmo com a próxima em rascunho ou revisão) e não foi desligado."""
    return bool(p.approved_manifest) and p.status != "disabled"


def _get(db, name: str) -> Plugin:
    p = db.scalar(select(Plugin).where(Plugin.name == name))
    if p is None:
        raise PlatformError(f"plugin '{name}' não existe")
    return p


def _builder(acc: Access) -> bool:
    return acc.p.is_admin or any(RANK[r] >= RANK["developer"] for r in acc.teams.values())


def _can_edit(acc: Access, p: Plugin) -> bool:
    if acc.p.is_admin:
        return True
    if p.team_id:
        return RANK.get(acc.teams.get(p.team_id, ""), 0) >= RANK["developer"]
    return p.created_by == acc.p.name


def _can_install(acc: Access, team_id: int | None) -> bool:
    if acc.p.is_admin:
        return True
    return team_id is not None and acc.teams.get(team_id) == "maintainer"


def _team_name(db, team_id) -> str | None:
    t = db.get(Team, team_id) if team_id else None
    return t.slug if t else None


def install_dict(db, i: PluginInstall, p: Plugin) -> dict:
    m = p.approved_manifest or {}
    secret_keys = [s["key"] for s in m.get("settings") or [] if s.get("secret")]
    have = _secrets(i)
    return {"team": _team_name(db, i.team_id), "scope": "team" if i.team_id else "org", "enabled": i.enabled,
            "settings": i.settings or {}, "credential": bool(have.get("credential")),
            "secrets": {k: bool((have.get("settings") or {}).get(k)) for k in secret_keys},
            "stats": i.stats or {}, "last_test": i.last_test, "installed_by": i.installed_by,
            "installed_at": iso(i.installed_at) if i.installed_at else None}


def plugin_dict(db, acc: Access, p: Plugin, detail: bool = False) -> dict:
    m = p.approved_manifest or p.manifest
    d = {"name": p.name, "live": live(p), "title": p.title, "description": p.description, "version": p.version, "status": p.status,
         "approved_version": p.approved_version, "source": p.source, "team": _team_name(db, p.team_id),
         "publisher": m.get("publisher", ""), "permissions": permissions(m), "can_edit": _can_edit(acc, p),
         "installed_for": [_team_name(db, i.team_id) or "org" for i in
                           db.scalars(select(PluginInstall).where(PluginInstall.plugin_id == p.id))],
         "created_by": p.created_by, "updated_at": iso(p.updated_at) if p.updated_at else None}
    if detail:
        d.update(manifest=p.manifest, approved_manifest=p.approved_manifest, approved_by=p.approved_by,
                 approved_at=iso(p.approved_at) if p.approved_at else None, review_note=p.review_note,
                 submitted_by=p.submitted_by, draft_permissions=permissions(p.manifest),
                 can_review=acc.p.is_admin and p.status == "pending" and acc.p.name not in (p.submitted_by, p.created_by),
                 installs=[install_dict(db, i, p) for i in db.scalars(select(PluginInstall).where(
                     PluginInstall.plugin_id == p.id)) if acc.p.is_admin or i.team_id is None or i.team_id in acc.teams],
                 install_teams=[{"slug": _team_name(db, t), "role": r} for t, r in acc.teams.items() if r == "maintainer"],
                 yaml=yaml.safe_dump(p.manifest, sort_keys=False, allow_unicode=True))
    return d


def list_plugins(db, acc: Access) -> list[dict]:
    out = []
    for p in db.scalars(select(Plugin).order_by(Plugin.name)):
        if live(p) or _can_edit(acc, p) or acc.p.is_admin:
            out.append(plugin_dict(db, acc, p))
    return out


def get_plugin(db, acc: Access, name: str) -> dict:
    p = _get(db, name)
    if not live(p) and not (_can_edit(acc, p) or acc.p.is_admin):
        raise Forbidden(f"plugin '{name}' não encontrado ou sem acesso")
    return plugin_dict(db, acc, p, detail=True)


# ------------------------------------------------------------------ ciclo de vida
def create(db, acc: Access, manifest, team: str | None = None, source: str = "manual") -> dict:
    if not _builder(acc):
        raise Forbidden("só quem constrói agentes (developer ou admin) cria plugins")
    m = parse(manifest)
    if db.scalar(select(Plugin.id).where(Plugin.name == m["name"])):
        raise PlatformError(f"já existe um plugin '{m['name']}': edite-o (PUT) para mandar uma versão nova")
    team_id = None
    if team:
        t = find_team(db, team)
        if not acc.p.is_admin and RANK.get(acc.teams.get(t.id, ""), 0) < RANK["developer"]:
            raise Forbidden(f"você não é developer do time '{t.slug}'")
        team_id = t.id
    p = Plugin(name=m["name"], title=m.get("title") or m["name"], description=m.get("description", ""),
               version=m["version"], manifest=m, status="draft", source=source if source in ("manual", "openapi") else "manual",
               team_id=team_id, created_by=acc.p.name, created_at=now(), updated_at=now())
    db.add(p)
    db.commit()
    audit(db, acc.p.name, "plugin.create", p.name, f"v{p.version}")
    return plugin_dict(db, acc, p, detail=True)


def update(db, acc: Access, name: str, manifest) -> dict:
    p = _get(db, name)
    if not _can_edit(acc, p):
        raise Forbidden("só o time dono do plugin (ou um admin) edita")
    m = parse(manifest)
    if m["name"] != p.name:
        raise PlatformError("o nome do plugin não muda (crie outro)")
    if p.approved_version and m["version"] == p.approved_version and m != p.approved_manifest:
        raise PlatformError(f"a v{p.approved_version} já foi aprovada: suba a versão do manifesto")
    p.manifest, p.version, p.title, p.description = m, m["version"], m.get("title") or p.name, m.get("description", "")
    if p.status != "disabled":
        p.status = "approved" if p.approved_manifest == m else "draft"
    p.updated_at = now()
    db.commit()
    audit(db, acc.p.name, "plugin.update", p.name, f"v{p.version}")
    return plugin_dict(db, acc, p, detail=True)


def submit(db, acc: Access, name: str) -> dict:
    p = _get(db, name)
    if not _can_edit(acc, p):
        raise Forbidden("só o time dono do plugin envia para revisão")
    if p.status not in ("draft", "rejected"):
        raise PlatformError(f"plugin está {p.status}: nada para enviar")
    p.status, p.submitted_by, p.review_note, p.updated_at = "pending", acc.p.name, "", now()
    db.commit()
    audit(db, acc.p.name, "plugin.submit", p.name, f"v{p.version}")
    return plugin_dict(db, acc, p, detail=True)


def _classify(db, m: dict):
    """A alçada já nasce certa: cada ferramenta entra no catálogo de ações com o tipo e o risco do manifesto."""
    for t in m["tools"]:
        ref = f"mcp:plugin-{m['name']}:{t['name']}"
        row = db.scalar(select(ActionCatalog).where(ActionCatalog.tool_ref == ref))
        if row is None:
            row = ActionCatalog(tool_ref=ref)
            db.add(row)
        row.action_type, row.risk = t["action"], t.get("risk") or gatemod.RISK[t["action"]]
        row.reversible, row.classified_by, row.updated_at = bool(t.get("reversible")), f"plugin:{m['name']}@{m['version']}", now()


def review(db, acc: Access, name: str, decision: str, note: str = "") -> dict:
    p = _get(db, name)
    if not acc.p.is_admin:
        raise Forbidden("só um admin aprova plugins")
    if p.status != "pending":
        raise PlatformError(f"plugin está {p.status}, não aguardando revisão")
    if acc.p.name in (p.submitted_by, p.created_by):
        raise Forbidden("quatro olhos: quem criou ou enviou o plugin não aprova")
    if decision not in ("approve", "reject"):
        raise PlatformError("decision = approve | reject")
    if decision == "reject" and not note.strip():
        raise PlatformError("diga o que mudar (note)")
    p.review_note = note.strip()[:2000]
    if decision == "approve":
        p.approved_manifest, p.approved_version = copy.deepcopy(p.manifest), p.version
        p.approved_by, p.approved_at, p.status = acc.p.name, now(), "approved"
        _classify(db, p.manifest)
    else:
        p.status = "rejected"
    p.updated_at = now()
    db.commit()
    audit(db, acc.p.name, f"plugin.{decision}", p.name, f"v{p.version} {note[:200]}")
    return plugin_dict(db, acc, p, detail=True)


def set_disabled(db, acc: Access, name: str, disabled: bool) -> dict:
    if not acc.p.is_admin:
        raise Forbidden("só um admin desliga um plugin")
    p = _get(db, name)
    p.status = "disabled" if disabled else ("approved" if p.approved_manifest else "draft")
    p.updated_at = now()
    db.commit()
    audit(db, acc.p.name, "plugin.disable" if disabled else "plugin.enable", p.name)
    return plugin_dict(db, acc, p, detail=True)


def delete(db, acc: Access, name: str):
    p = _get(db, name)
    if not (acc.p.is_admin or (_can_edit(acc, p) and not p.approved_manifest)):
        raise Forbidden("só um admin apaga um plugin que já foi aprovado")
    db.delete(p)
    db.commit()
    audit(db, acc.p.name, "plugin.delete", name)


# ------------------------------------------------------------------ instalação por time
def _secrets(i: PluginInstall) -> dict:
    try:
        return json.loads(crypto.decrypt(i.secret)) if i.secret else {}
    except (ValueError, RuntimeError):
        return {}


def _install_row(db, p: Plugin, team_id: int | None) -> PluginInstall | None:
    q = select(PluginInstall).where(PluginInstall.plugin_id == p.id)
    q = q.where(PluginInstall.team_id == team_id) if team_id else q.where(PluginInstall.team_id.is_(None))
    return db.scalar(q)


def install(db, acc: Access, name: str, team: str | None, settings: dict | None = None, secrets: dict | None = None,
            credential: str | None = None, enabled: bool | None = None) -> dict:
    p = _get(db, name)
    if not live(p):
        raise PlatformError("só plugins aprovados (e ligados) são instalados")
    team_id = find_team(db, team).id if team else None
    if not _can_install(acc, team_id):
        raise Forbidden("instala o mantenedor do time (ou um admin, também para a empresa toda)")
    m = p.approved_manifest
    decl = {s["key"]: s for s in m.get("settings") or []}
    i = _install_row(db, p, team_id) or PluginInstall(plugin_id=p.id, team_id=team_id, installed_by=acc.p.name,
                                                       installed_at=now(), settings={}, enabled=True)
    plain, sec = dict(i.settings or {}), _secrets(i)
    sec.setdefault("settings", {})
    for k, v in (settings or {}).items():
        if k not in decl or decl[k].get("secret"):
            raise PlatformError(f"configuração '{k}' não existe neste plugin (as secretas vão em secrets)")
        plain[k] = v
    for k, v in (secrets or {}).items():
        if k not in decl or not decl[k].get("secret"):
            raise PlatformError(f"'{k}' não é uma configuração secreta deste plugin")
        if v:
            sec["settings"][k] = str(v)
    if credential is not None and credential != "":
        sec["credential"] = str(credential)
    if enabled is not None:
        i.enabled = bool(enabled)
    missing = [k for k, s in decl.items() if s.get("required") and not (plain.get(k) not in (None, "") or
                                                                         sec["settings"].get(k) or s.get("default") is not None)]
    if missing:
        raise PlatformError(f"faltam configurações obrigatórias: {', '.join(missing)}")
    if m["auth"]["type"] != "none" and not sec.get("credential"):
        raise PlatformError(f"falta a credencial ({m['auth'].get('label') or m['auth']['type']})")
    i.settings, i.secret = plain, crypto.encrypt(json.dumps(sec))
    if i.id is None:
        db.add(i)
    db.commit()
    audit(db, acc.p.name, "plugin.install", p.name, f"time {team or 'empresa'}")
    return install_dict(db, i, p)


def uninstall(db, acc: Access, name: str, team: str | None):
    p = _get(db, name)
    team_id = find_team(db, team).id if team else None
    if not _can_install(acc, team_id):
        raise Forbidden("desinstala o mantenedor do time (ou um admin)")
    i = _install_row(db, p, team_id)
    if i is None:
        raise PlatformError("não está instalado aqui")
    db.delete(i)
    db.commit()
    audit(db, acc.p.name, "plugin.uninstall", p.name, f"time {team or 'empresa'}")


def test_install(db, acc: Access, name: str, team: str | None) -> dict:
    p = _get(db, name)
    team_id = find_team(db, team).id if team else None
    if not _can_install(acc, team_id):
        raise Forbidden("testa quem instala (mantenedor do time ou admin)")
    i = _install_row(db, p, team_id)
    if i is None:
        raise PlatformError("instale antes de testar")
    m = p.approved_manifest
    t = m.get("test") or {"tool": next((x["name"] for x in m["tools"] if x["method"] == "GET"), m["tools"][0]["name"]),
                          "args": {}}
    tool = next(x for x in m["tools"] if x["name"] == t["tool"])
    if tool["method"] != "GET" and not m.get("test"):
        raise PlatformError("sem ferramenta de leitura para testar: declare `test` no manifesto")
    text, err, status = _execute(db, m, i, tool, t.get("args") or {})
    i.last_test = {"ok": not err, "status": status, "at": iso(now()), "tool": tool["name"], "sample": text[:300]}
    db.commit()
    return i.last_test


# ------------------------------------------------------------------ execução (sempre na central)
def _check_host(host: str):
    if config.PLUGIN_ALLOW_PRIVATE:
        return
    try:
        addrs = {x[4][0] for x in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        raise PlatformError(f"não foi possível resolver '{host}'") from None
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise PlatformError(f"'{host}' está numa rede interna: libere com PLUGIN_ALLOW_PRIVATE=1")


def _fill(text: str, values: dict) -> str:
    return _TPL.sub(lambda mt: str(values.get(mt.group(1), "")), text)


def _execute(db, m: dict, i: PluginInstall, tool: dict, args: dict) -> tuple[str, bool, int]:
    sec = _secrets(i)
    values = {s["key"]: s.get("default") for s in m.get("settings") or []}
    values.update(i.settings or {})
    values.update(sec.get("settings") or {})
    args = dict(args or {})
    path = tool["path"]
    for key in _PATH_PARAM.findall(path):
        if key not in args:
            return f"falta o parâmetro '{key}'", True, 0
        path = path.replace("{" + key + "}", urllib.parse.quote(str(args.pop(key)), safe=""))
    url = _fill(m["base_url"], values) + _fill(path, values)
    host = urllib.parse.urlparse(url).hostname or ""
    _check_host(host)
    headers = {"User-Agent": f"AgentHangar-Plugin/{m['name']}", "Accept": "application/json, text/plain, */*"}
    headers.update({k: _fill(v, values) for k, v in (tool.get("headers") or {}).items()})
    params = {}
    a, cred = m["auth"], sec.get("credential", "")
    if a["type"] == "bearer":
        headers["Authorization"] = f"Bearer {cred}"
    elif a["type"] == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    elif a["type"] == "api_key":
        (headers if a.get("in", "header") == "header" else params)[a["name"]] = cred
    kw = {"headers": headers}
    if tool["method"] in ("GET", "DELETE"):
        kw["params"] = {**params, **{k: v for k, v in args.items() if v is not None}}
    else:
        kw["params"], kw["json"] = params, args
    try:
        with HTTP() as http:
            r = http.request(tool["method"], url, **kw)
    except httpx.HTTPError as e:
        return f"falha ao chamar o sistema: {type(e).__name__}", True, 0
    text = r.text
    try:
        text = json.dumps(r.json(), ensure_ascii=False, indent=1)
    except ValueError:
        pass
    for s in sorted({cred, *(sec.get("settings") or {}).values()}, key=len, reverse=True):
        if s and len(str(s)) >= 4:  # um sistema que ecoa headers não devolve o segredo ao agente nem à tela
            text = text.replace(str(s), "[segredo]")
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n… [truncado: {len(text)} caracteres]"
    if r.is_redirect:
        return f"o sistema redirecionou ({r.status_code}); plugins não seguem redirecionamentos", True, r.status_code
    return (f"HTTP {r.status_code}: {text}" if r.status_code >= 400 else text), r.status_code >= 400, r.status_code


def _record(db, i: PluginInstall, err: bool, msg: str):
    st = dict(i.stats or {})
    st["calls"] = int(st.get("calls", 0)) + 1
    st["last_call"] = iso(now())
    if err:
        st["errors"] = int(st.get("errors", 0)) + 1
        st["last_error"] = msg[:300]
    i.stats = st
    db.commit()


def install_for(db, a: Agent, name: str) -> tuple[Plugin, PluginInstall]:
    p = db.scalar(select(Plugin).where(Plugin.name == name))
    if p is None or not live(p):
        raise PlatformError(f"plugin '{name}' não está aprovado ou foi desligado")
    i = (_install_row(db, p, a.team_id) if a.team_id else None) or _install_row(db, p, None)
    if i is None or not i.enabled:
        raise PlatformError(f"plugin '{name}' não está instalado para o time deste agente")
    return p, i


def resolve_for_spec(db, a: Agent, names: list[str]) -> tuple[list[dict], list[dict]]:
    """(mcps, skills) que entram na spec resolvida do agente para os plugins que ele usa."""
    mcps, skills = [], []
    for n in names or []:
        p, _ = install_for(db, a, n)
        mcps.append({"name": f"plugin-{n}", "url": f"{config.INTERNAL_BASE_URL}/internal/plugins/{n}/mcp"})
        skills += [{"name": f"{n}:{s['name']}", "description": s.get("description", ""), "content": s["content"]}
                   for s in p.approved_manifest.get("skills") or []]
    return mcps, skills


def mcp_tools(m: dict) -> list[dict]:
    return [{"name": t["name"], "description": (t.get("description") or f"{t['method']} {t['path']}")[:1000],
             "inputSchema": t.get("parameters") or {"type": "object", "properties": {}}} for t in m["tools"]]


def mcp_handle(db, a: Agent, specs: list[dict], name: str, msg: dict) -> dict | None:
    """Um servidor MCP mínimo (sem estado, respostas JSON) para o plugin, só para agentes que o declaram na spec."""
    if not any(name in (s.get("plugins") or []) for s in specs):
        raise Forbidden(f"'{a.slug}' não declara o plugin '{name}' na spec")
    p, i = install_for(db, a, name)
    m = p.approved_manifest
    mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
    if mid is None:  # notificação (ex.: notifications/initialized)
        return None
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") or "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": f"plugin-{name}", "version": p.approved_version}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": mcp_tools(m)}
    elif method == "tools/call":
        tool = next((t for t in m["tools"] if t["name"] == params.get("name")), None)
        if tool is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "ferramenta desconhecida"}}
        try:
            text, err, _ = _execute(db, m, i, tool, params.get("arguments") or {})
        except PlatformError as e:
            text, err = str(e), True
        _record(db, i, err, text)
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método '{method}' não suportado"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


