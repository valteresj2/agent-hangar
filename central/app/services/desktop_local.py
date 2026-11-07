"""O computador da pessoa como desktop do Digital employee: o app Agent Hangar Desktop trabalha como o posto (worker
externo) e opera a tela da máquina onde está instalado — só nos apps que a pessoa liberou ali, com um aviso na tela e
um botão de parar. As ferramentas são as mesmas do desktop da plataforma (desktop_open, desktop_look, desktop_click…),
executadas no app; este módulo é a alçada delas, com as mesmas regras (services/desktop.py):

- antes de cada ação que pode mudar algo (abrir, clicar, digitar, tecla) o posto pergunta no /gate com
  `tool: "desktop:<ação>"`, a janela em que vai agir e, quando a ação pode confirmar algo, a captura dessa janela;
- clique/tecla/Enter que confirma (salvar, confirmar, enviar, pagar…) passa pela alçada do cargo com a captura no
  pedido; o clique acontece onde a pessoa aprovou (`where` na resposta);
- cada ação liberada vira um evento `desktop` na linha do tempo da tarefa (o posto completa a janela depois dela pelo
  /progress, para a regra da nova tentativa);
- `secret://nome` é resolvido aqui e vai só na resposta ao posto autenticado: a linha do tempo registra "[segredo]" e
  o valor nunca entra na conversa (o app só digita num campo de senha).
"""
import base64
import binascii
import json

from ..models import TaskEvent, now
from . import desktop
from .common import PlatformError

ACTIONS = ("open", "click", "type", "key", "screenshot")
MAX_SHOT = 4_000_000  # caracteres base64 (~3 MB de PNG): a captura de uma janela, reduzida pelo app


def _shot(screenshot: str) -> str:
    s = (screenshot or "").strip()
    if not s:
        return ""
    if len(s) > MAX_SHOT:
        raise PlatformError("captura grande demais: mande a janela reduzida (até ~3 MB)")
    try:
        base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise PlatformError("captura inválida: PNG em base64") from None
    return s


def _event(ctx, action: str, target: str = "", value: str = "", window: str = "", **extra) -> int:
    machine = str((ctx.e.worker_info or {}).get("name") or "")[:120]
    ev = TaskEvent(task_id=ctx.task.id, kind="desktop", payload={
        "action": action, "target": target[:200], "value": value[:200], "window": window[:200], "local": True,
        **({"machine": machine} if machine else {}), **extra})
    ctx.db.add(ev)
    ctx.task.updated_at = now()
    ctx.db.commit()
    return ev.id


def _held(h) -> dict:
    if isinstance(h, str):  # a regra segurou com uma explicação (ex.: confirmação repetida): não execute
        return {"status": "denied", "message": h}
    return h


def gate(db, e, a, t, action: str, args: dict, rationale: str = "", screenshot: str = "") -> dict:
    from . import governance
    from .platform_tools import Ctx
    if action not in ACTIONS:
        raise PlatformError(f"desktop:<ação> com ação em {', '.join(ACTIONS)} (olhar e rolar não pedem alçada)")
    if e.status in ("paused", "offboarded"):
        return {"status": "denied", "message": f"Digital employee {e.status}: nenhuma ação é executada."}
    args = governance.unmask(db, t.id, args or {})
    ctx = Ctx(db, e, a, t, rationale)
    window = str(args.get("window") or "")
    shot = _shot(screenshot)

    def look():
        return {"window": window, "screenshot": shot}

    if action == "open":
        app = str(args.get("app") or "").strip()
        if not app:
            raise PlatformError("diga o app (app)")
        return {"status": "allowed", "event": _event(ctx, "open", app, window=window)}
    if action == "screenshot":
        if not shot:
            raise PlatformError("mande a captura (screenshot)")
        name = desktop._evidence(ctx, {"screenshot": shot}, "captura pedida pelo funcionário")
        _event(ctx, "screenshot", name, window=window)
        return {"status": "allowed", "file": name}
    if action == "click":
        label = str(args.get("label") or "")
        where = {k: args[k] for k in ("element", "x", "y") if args.get(k) not in (None, "")}
        d = desktop.decide_click(ctx, label, where, bool(args.get("commit")), bool(args.get("repeat")), look)
        if "held" in d:
            return _held(d["held"])
        ev = _event(ctx, "click", label, json.dumps(d["where"]), d["window"] or window, **desktop.marks(d))
        return {"status": "allowed", "where": d["where"], "approved": d["approved"], "covered_by": d["covered"],
                "event": ev}
    if action == "type":
        text = str(args.get("text") or "")
        real, shown, secret = text, text, text.startswith("secret://")
        if secret:
            from . import secrets_vault
            real = secrets_vault.resolve(text, a.team_id, f"desktop:{a.slug}", db)
            shown = "[segredo]"
        d = desktop.decide_type(ctx, real, shown, look)
        if "held" in d:
            return _held(d["held"])
        ev = _event(ctx, "type", str(args.get("label") or ""), shown if secret else shown[:60], d["window"] or window,
                    **desktop.marks(d))
        out = {"status": "allowed", "approved": d["approved"], "covered_by": d["covered"], "event": ev}
        if real != text or secret:
            out["text"] = real  # o valor real (segredo ou dado mascarado pelo DLP): só para o posto digitar
        if secret:
            out["secret"] = True
        return out
    key, mods = str(args.get("key") or ""), [str(m) for m in args.get("modifiers") or []]
    if not key:
        raise PlatformError("diga a tecla (key)")
    d = desktop.decide_key(ctx, key, mods, bool(args.get("commit")), look)
    if "held" in d:
        return _held(d["held"])
    ev = _event(ctx, "key", d["combo"], window=d["window"] or window, **desktop.marks(d))
    return {"status": "allowed", "approved": d["approved"], "covered_by": d["covered"], "event": ev}


def after(db, t, info: dict) -> None:
    """A janela depois da ação (o /progress do posto): a regra da nova tentativa compara com a de antes."""
    try:
        eid = int(info.get("event") or 0)
    except (TypeError, ValueError):
        return
    ev = db.get(TaskEvent, eid) if eid else None
    if ev is None or ev.task_id != t.id or ev.kind != "desktop":
        return
    p = dict(ev.payload or {})
    p["after"] = str(info.get("after") or "")[:200]
    if info.get("ok") is False:
        p["failed"] = str(info.get("error") or "falhou")[:200]
    ev.payload = p
