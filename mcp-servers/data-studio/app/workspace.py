"""Workspace por sessão (conversa): diretório próprio, dono próprio (uid dedicado) e links de download assinados.

A sessão vem do header X-Session-Id que o runtime do Agent Hangar repassa (no LibreChat, o id da conversa).
Os links são /f/<sid>/<token>/<arquivo>, com token = HMAC(segredo, sid): quem não recebeu o link não adivinha.
"""
import base64
import hashlib
import hmac
import mimetypes
import os
import re
import secrets
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR", "/data"))
SESSIONS = DATA / "sessions"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8095").rstrip("/")
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "200"))
UID_BASE = 20000

TABULAR = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".parquet", ".json", ".jsonl", ".ndjson"}

mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx")
mimetypes.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
mimetypes.add_type("application/vnd.apache.parquet", ".parquet")


def _secret() -> bytes:
    env = os.environ.get("FILES_SECRET")
    if env:
        return env.encode()
    f = DATA / ".files_secret"
    if not f.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip().encode()


SECRET = _secret()


def session_id(raw: str | None) -> str:
    raw = (raw or "").strip() or "default"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def session_uid(sid: str) -> int:
    return UID_BASE + int(sid[:8], 16) % 30000


def workspace(sid: str) -> Path:
    """Cria o diretório da sessão com dono = uid da sessão e modo 700: o Python de uma conversa não lê a outra."""
    p = SESSIONS / sid
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            uid = session_uid(sid)
            os.chown(p, uid, uid)
        p.chmod(0o700)
    return p


def fix_owner(sid: str, path: Path):
    if os.geteuid() == 0 and path.exists():
        uid = session_uid(sid)
        os.chown(path, uid, uid)


def token(sid: str) -> str:
    return hmac.new(SECRET, sid.encode(), hashlib.sha256).hexdigest()[:24]


def verify(sid: str, tok: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{20}", sid)) and hmac.compare_digest(token(sid), tok)


def url(sid: str, rel: str) -> str:
    from urllib.parse import quote
    return f"{PUBLIC_URL}/f/{sid}/{token(sid)}/{quote(rel)}"


def safe_name(name: str) -> str:
    name = os.path.basename(name or "arquivo").strip().replace(" ", "_")
    name = re.sub(r"[^\w.\-()]", "_", name, flags=re.UNICODE)
    return name[:120] or "arquivo"


def resolve(sid: str, rel: str) -> Path:
    """Caminho dentro do workspace (nunca fora dele)."""
    base = workspace(sid).resolve()
    p = (base / rel.lstrip("/")).resolve()
    if base != p and base not in p.parents:
        raise ValueError(f"caminho fora do workspace: {rel}")
    return p


def unique_path(sid: str, name: str) -> Path:
    p = resolve(sid, safe_name(name))
    stem, suf, i = p.stem, p.suffix, 2
    while p.exists():
        p = p.with_name(f"{stem}_{i}{suf}")
        i += 1
    return p


def ingest(sid: str, filename: str, data_b64: str) -> tuple[Path, bool]:
    """Grava um anexo. Se o mesmo conteúdo já existe (o LibreChat reenvia anexos a cada turno), reaproveita."""
    if "," in data_b64[:200] and data_b64.startswith("data:"):
        data_b64 = data_b64.split(",", 1)[1]
    raw = base64.b64decode(data_b64)
    if len(raw) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"arquivo maior que {MAX_FILE_MB} MB")
    digest = hashlib.sha256(raw).hexdigest()
    ws = workspace(sid)
    index = ws / ".ingested"
    known = dict(line.split(" ", 1) for line in index.read_text().splitlines() if " " in line) if index.exists() else {}
    if digest in known and (ws / known[digest]).exists():
        return ws / known[digest], False
    name = safe_name(filename)
    target = ws / name
    if target.exists():
        target = unique_path(sid, name)
    target.write_bytes(raw)
    with index.open("a") as f:
        f.write(f"{digest} {target.name}\n")
    fix_owner(sid, target)
    fix_owner(sid, index)
    return target, True


def listing(sid: str) -> list[dict]:
    ws = workspace(sid)
    out = []
    for p in sorted(ws.rglob("*")):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ws).parts):
            rel = p.relative_to(ws).as_posix()
            out.append({"path": rel, "bytes": p.stat().st_size,
                        "type": mimetypes.guess_type(p.name)[0] or "application/octet-stream", "url": url(sid, rel)})
    return out


def snapshot(sid: str) -> dict[str, float]:
    ws = workspace(sid)
    return {p.relative_to(ws).as_posix(): p.stat().st_mtime for p in ws.rglob("*")
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ws).parts)}


def changed(sid: str, before: dict[str, float]) -> list[dict]:
    after = snapshot(sid)
    return [{"path": k, "url": url(sid, k)} for k, v in sorted(after.items()) if before.get(k) != v]


# ------------------------------------------------------------------ retenção
RETENTION_DAYS = float(os.environ.get("RETENTION_DAYS", "30"))  # 0 = nunca apaga


def touch(sid: str):
    """Marca uso da sessão (a retenção conta a partir do último uso, não da criação)."""
    marker = workspace(sid) / ".last_used"
    marker.touch()
    fix_owner(sid, marker)


def last_used(p: Path) -> float:
    marker = p / ".last_used"
    return (marker if marker.exists() else p).stat().st_mtime


def expired(now: float | None = None) -> list[str]:
    import time
    if RETENTION_DAYS <= 0 or not SESSIONS.exists():
        return []
    limit = (now or time.time()) - RETENTION_DAYS * 86400
    return [p.name for p in SESSIONS.iterdir() if p.is_dir() and last_used(p) < limit]


def purge(sid: str):
    import shutil
    shutil.rmtree(SESSIONS / sid, ignore_errors=True)
