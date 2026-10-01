"""`hangar backup`, `restore` e `upgrade`: comandos do pg_dump/pg_restore (Docker e Kubernetes), arquivo gravado só
quando o dump dá certo, backup de segurança antes de restaurar e upgrade que exige versão com imagens publicadas."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cli"))
from hangar_cli import backup as bk  # noqa: E402
from hangar_cli import setup as st  # noqa: E402


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / ".env").write_text("POSTGRES_USER=central\nPOSTGRES_DB=central\nHANGAR_REGISTRY=ghcr.io/acme\nHANGAR_VERSION=0.11.0\n")
    return tmp_path


def test_commands(repo, monkeypatch):
    assert bk.dump_cmd(repo)[:5] == ["docker", "compose", "exec", "-T", "postgres"]
    assert bk.dump_cmd(repo)[-4:] == ["central", "--format=custom", "--no-owner", "central"]
    assert "--single-transaction" in bk.restore_cmd(repo) and "--clean" in bk.restore_cmd(repo)
    monkeypatch.setattr(bk, "_k8s_pod", lambda ns, rel: "hangar-agent-hangar-postgres-0")
    k = bk.dump_cmd(repo, "ia", "hangar")
    assert k[:6] == ["kubectl", "-n", "ia", "exec", "-i", "hangar-agent-hangar-postgres-0"] and "pg_dump" in k


class _Run:
    def __init__(self, rc=0, data=b"PGDMP-fake"):
        self.rc, self.data, self.calls = rc, data, []

    def __call__(self, cmd, cwd=None, stdout=None, stderr=None, stdin=None, check=False, **kw):
        self.calls.append(cmd)
        if stdout is not None and "pg_dump" in cmd:
            stdout.write(self.data if self.rc == 0 else b"")
        return subprocess.CompletedProcess(cmd, self.rc, b"", b"erro simulado")


def test_backup_writes_only_on_success(repo, monkeypatch):
    monkeypatch.setattr(bk.subprocess, "run", _Run())
    f = bk.backup(repo, quiet=True)
    assert f.parent == repo / ".hangar" / "backups" and f.read_bytes() == b"PGDMP-fake" and f.name.endswith("-manual.dump")
    monkeypatch.setattr(bk.subprocess, "run", _Run(rc=1))
    with pytest.raises(st.SetupError, match="pg_dump falhou"):
        bk.backup(repo, quiet=True)
    assert len(list((repo / ".hangar" / "backups").glob("*"))) == 1  # nada de arquivo pela metade


def test_restore_takes_safety_backup_first(repo, monkeypatch):
    run = _Run()
    monkeypatch.setattr(bk.subprocess, "run", run)
    src = repo / "old.dump"
    src.write_bytes(b"PGDMP")
    assert bk.restore(repo, str(src), assume_yes=True) == 0
    kinds = [c[4] if c[:2] == ["docker", "compose"] and len(c) > 4 else c[2] for c in run.calls]
    assert kinds[0] == "postgres" and "pg_dump" in run.calls[0]          # 1º: backup de segurança
    assert ["docker", "compose", "stop", "central"] in run.calls
    assert any("pg_restore" in c for c in run.calls) and ["docker", "compose", "start", "central"] in run.calls
    assert any(p.name.endswith("antes-de-restaurar.dump") for p in (repo / ".hangar" / "backups").iterdir())
    with pytest.raises(st.SetupError, match="não encontrado"):
        bk.restore(repo, str(repo / "nao-existe.dump"), assume_yes=True)


def test_upgrade(repo, monkeypatch):
    with pytest.raises(st.SetupError, match="--version"):
        bk.upgrade(repo, None, assume_yes=True)
    run = _Run()
    monkeypatch.setattr(bk.subprocess, "run", run)
    monkeypatch.setattr(bk, "wait_healthy", lambda base: True)
    import hangar_cli.doctor as dr
    monkeypatch.setattr(dr, "doctor", lambda root: 0)
    assert bk.upgrade(repo, "0.12.0", assume_yes=True) == 0
    assert st.read_env(repo / ".env")["HANGAR_VERSION"] == "0.12.0"
    assert ["docker", "compose", "up", "-d"] in run.calls
    assert any(p.name.endswith("antes-de-0.12.0.dump") for p in (repo / ".hangar" / "backups").iterdir())
    assert bk.upgrade(repo, None, namespace="ia") == 0  # Kubernetes: só o passo a passo
