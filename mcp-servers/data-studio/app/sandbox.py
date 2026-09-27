"""Backend "container": um container sandbox por sessão (conversa) para o kernel Python.

O sandbox usa esta mesma imagem, mas:
- monta SÓ o diretório da sessão (volume subpath: sessions/<sid> → /ws; exige Docker Engine 26+);
- roda com o uid da sessão, sem capabilities, com no-new-privileges e FS raiz somente leitura (+ /tmp tmpfs);
- tem limites próprios de memória, CPU e processos (SANDBOX_MEM, SANDBOX_CPUS, SANDBOX_PIDS);
- fica numa rede própria (SANDBOX_NETWORK), com saída para a internet e sem acesso à rede dos agentes.
O servidor fala com o kernel pelas portas ZeroMQ dessa rede e com o Docker por um socket proxy dedicado.
"""
import logging
import os
import threading

import docker
from docker.types import Mount

from . import workspace as ws
from .kernels import Kernel

log = logging.getLogger("data-studio.sandbox")
IMAGE = os.environ.get("SANDBOX_IMAGE", "agent-hangar/mcp-data-studio:latest")
VOLUME = os.environ.get("SANDBOX_VOLUME", "hangar_data_studio")
NETWORK = os.environ.get("SANDBOX_NETWORK", "hangar_sandbox")
MEM = os.environ.get("SANDBOX_MEM", "2g")
CPUS = float(os.environ.get("SANDBOX_CPUS", "1.0"))
PIDS = int(os.environ.get("SANDBOX_PIDS", "256"))
LABEL = "hangar.data-studio.sandbox"

_client = None
_lock = threading.Lock()


def client():
    global _client
    with _lock:
        if _client is None:
            _client = docker.from_env(version="auto")  # "auto": o subpath de volume precisa da API >= 1.45
        return _client


def container_name(sid: str) -> str:
    return f"ds-sbx-{sid}"


def cleanup():
    """Remove sandboxes que sobraram (ex.: o servidor reiniciou)."""
    try:
        for c in client().containers.list(all=True, filters={"label": LABEL}):
            c.remove(force=True, v=True)
    except Exception as e:
        log.warning("limpeza de sandboxes falhou: %s", e)


class ContainerKernel(Kernel):
    bind_ip = "0.0.0.0"  # o kernel escuta na rede do sandbox; o servidor conecta pelo nome do container

    def _launch(self, home, conn) -> str:
        name = container_name(self.sid)
        c = client()
        try:
            c.containers.get(name).remove(force=True, v=True)
        except docker.errors.NotFound:
            pass
        uid = ws.session_uid(self.sid)
        mount = Mount(target="/ws", source=VOLUME, type="volume")
        mount["VolumeOptions"] = {"Subpath": f"sessions/{self.sid}"}
        env = {**self.kernel_env("/ws"), "PYTHONDONTWRITEBYTECODE": "1"}
        self.container = c.containers.run(
            IMAGE, ["python", "-m", "ipykernel_launcher", "-f", "/ws/.kernel.json"],
            name=name, hostname=name, detach=True, user=f"{uid}:{uid}", working_dir="/ws",
            environment=env, mounts=[mount], network=NETWORK, labels={LABEL: self.sid},
            mem_limit=MEM, nano_cpus=int(CPUS * 1e9), pids_limit=PIDS,
            cap_drop=["ALL"], security_opt=["no-new-privileges"], read_only=True,
            tmpfs={"/tmp": "size=512m"}, healthcheck={"test": ["NONE"]}, restart_policy={"Name": "no"},
        )
        return name

    def _interrupt(self):
        self.container.kill(signal="SIGINT")

    def alive(self) -> bool:
        try:
            self.container.reload()
            return self.container.status == "running"
        except docker.errors.NotFound:
            return False

    def _kill(self):
        try:
            self.container.remove(force=True, v=True)
        except docker.errors.NotFound:
            pass
