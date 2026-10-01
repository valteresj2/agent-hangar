"""Backup, restauração e atualização da instalação (`hangar backup`, `hangar restore`, `hangar upgrade`).

O que importa guardar:
- o banco (agentes, versões, catálogo, usuários, uso, auditoria): `pg_dump` no formato custom, em .hangar/backups/;
- a chave HANGAR_SECRET_KEY do .env (ou do Secret no Kubernetes): sem ela, as chaves de LLM salvas no banco não
  abrem. Ela NÃO vai dentro do arquivo de backup — guarde o .env num cofre, separado dos backups.
A memória dos agentes (Neo4j/FalkorDB) fica fora: use o backup do próprio banco de grafo (docs/backup.md).
"""
import subprocess
import time
from pathlib import Path

from .setup import SetupError, fail, info, ok, read_env, title, wait_healthy, warn, write_env, yes


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _dir(root: Path, out: str | None) -> Path:
    d = Path(out) if out else root / ".hangar" / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pg(root: Path) -> tuple[str, str]:
    env = read_env(root / ".env")
    return env.get("POSTGRES_USER") or "hangar", env.get("POSTGRES_DB") or "hangar"


def _k8s_pod(namespace: str, release: str) -> str:
    from . import kube
    pod = f"{kube.fullname(release)}-postgres-0"
    r = subprocess.run(["kubectl", "-n", namespace, "get", "pod", pod, "-o", "name"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SetupError(f"Postgres do chart não encontrado ({pod}). Com banco gerenciado, use os backups da nuvem "
                         "ou o backup do chart (backup.enabled=true) — ver docs/backup.md")
    return pod


def dump_cmd(root: Path, namespace: str | None = None, release: str = "agent-hangar") -> list[str]:
    if namespace:
        return ["kubectl", "-n", namespace, "exec", "-i", _k8s_pod(namespace, release), "--",
                "pg_dump", "-U", "hangar", "--format=custom", "--no-owner", "hangar"]
    user, db = _pg(root)
    return ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", user, "--format=custom", "--no-owner", db]


def restore_cmd(root: Path, namespace: str | None = None, release: str = "agent-hangar") -> list[str]:
    if namespace:
        return ["kubectl", "-n", namespace, "exec", "-i", _k8s_pod(namespace, release), "--",
                "pg_restore", "-U", "hangar", "-d", "hangar", "--clean", "--if-exists", "--no-owner", "--single-transaction"]
    user, db = _pg(root)
    return ["docker", "compose", "exec", "-T", "postgres", "pg_restore", "-U", user, "-d", db, "--clean", "--if-exists",
            "--no-owner", "--single-transaction"]


def backup(root: Path, out: str | None = None, namespace: str | None = None, release: str = "agent-hangar",
           reason: str = "manual", quiet: bool = False) -> Path:
    root = root.resolve()
    f = _dir(root, out) / f"hangar-{_stamp()}-{reason}.dump"
    with open(f.with_suffix(".tmp"), "wb") as fh:
        r = subprocess.run(dump_cmd(root, namespace, release), cwd=root, stdout=fh, stderr=subprocess.PIPE)
    if r.returncode != 0 or f.with_suffix(".tmp").stat().st_size == 0:
        f.with_suffix(".tmp").unlink(missing_ok=True)
        raise SetupError("pg_dump falhou: " + r.stderr.decode(errors="replace")[-400:])
    f.with_suffix(".tmp").replace(f)
    if not quiet:
        ok(f"backup: {f} ({f.stat().st_size / 1024:.0f} KB)")
        info("A chave HANGAR_SECRET_KEY (.env ou Secret do Kubernetes) não vai no backup: guarde-a num cofre, separada.")
    return f


def restore(root: Path, file: str, namespace: str | None = None, release: str = "agent-hangar",
            assume_yes: bool = False) -> int:
    root, src = root.resolve(), Path(file)
    if not src.is_file():
        raise SetupError(f"arquivo não encontrado: {src}")
    title("Restaurar o banco")
    warn(f"Isto SUBSTITUI o banco atual pelo conteúdo de {src.name}.")
    if not assume_yes and not yes("Continuar? (antes, é feito um backup do estado atual)", False):
        return 1
    safety = backup(root, None, namespace, release, "antes-de-restaurar", quiet=True)
    ok(f"estado atual guardado em {safety}")
    if not namespace:
        subprocess.run(["docker", "compose", "stop", "central"], cwd=root, check=False)
    with open(src, "rb") as fh:
        r = subprocess.run(restore_cmd(root, namespace, release), cwd=root, stdin=fh, stderr=subprocess.PIPE)
    if not namespace:
        subprocess.run(["docker", "compose", "start", "central"], cwd=root, check=False)
    else:
        from . import kube
        subprocess.run(["kubectl", "-n", namespace, "rollout", "restart", f"deploy/{kube.fullname(release)}-central"], check=False)
    if r.returncode != 0:
        fail("pg_restore falhou: " + r.stderr.decode(errors="replace")[-400:])
        info(f"O backup do estado anterior está em {safety}")
        return 1
    ok("banco restaurado; a central foi reiniciada (as migrações rodam sozinhas se o backup for de uma versão anterior)")
    info("Use o mesmo HANGAR_SECRET_KEY da época do backup, senão as chaves de LLM salvas não abrem.")
    return 0


def upgrade(root: Path, version: str | None, assume_yes: bool = False, namespace: str | None = None) -> int:
    """Docker: backup -> nova versão das imagens (publicadas) ou rebuild (código local) -> sobe -> confere."""
    root = root.resolve()
    if namespace:
        title("Atualizar no Kubernetes")
        info("1. git pull (ou baixe o chart da versão nova: oci://ghcr.io/valteresj2/charts/agent-hangar)")
        info("2. hangar setup --target kubernetes   (helm upgrade; com backup.enabled, o chart faz um pg_dump antes)")
        info(f"3. hangar doctor --namespace {namespace}")
        return 0
    env = read_env(root / ".env")
    published = "/" in (env.get("HANGAR_REGISTRY") or "agent-hangar")  # ghcr.io/<dono> ou espelho; "agent-hangar" = build local
    current = env.get("HANGAR_VERSION") or "latest"
    title("Atualizar o Agent Hangar")
    if published and not version:
        raise SetupError("informe a versão: hangar upgrade --version 0.12.0 (veja as releases no GitHub)")
    info(f"de {current} para {version or 'o código desta pasta (git pull feito?)'}")
    if not assume_yes and not yes("Continuar? (backup antes, automático)", True):
        return 1
    f = backup(root, reason=f"antes-de-{version or 'upgrade'}", quiet=True)
    ok(f"backup: {f}")
    if published:
        write_env(root / ".env", {"HANGAR_VERSION": version})
        subprocess.run(["docker", "compose", "pull", "--ignore-pull-failures"], cwd=root, check=False)
        r = subprocess.run(["docker", "compose", "up", "-d"], cwd=root)
    else:
        r = subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=root)
    if r.returncode != 0:
        fail("docker compose falhou — para voltar: restaure o .env.bak-* mais recente e rode  hangar restore " + str(f))
        return 1
    base = f"http://localhost:{env.get('CENTRAL_PORT') or 8090}"
    if not wait_healthy(base):
        fail(f"a central não respondeu em {base} — veja  docker compose logs central")
        info(f"Para voltar: HANGAR_VERSION={current} no .env, docker compose up -d e  hangar restore {f}")
        return 1
    ok("central no ar; conferindo a instalação…")
    from .doctor import doctor
    return doctor(root)
