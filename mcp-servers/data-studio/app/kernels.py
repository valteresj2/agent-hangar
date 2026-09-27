"""Kernels Jupyter (ipykernel) com estado, um por sessão — o equivalente à "execução de código" do Claude.

Cada kernel roda com o uid da sessão (setpriv), com HOME/cwd no workspace da sessão: variáveis sobrevivem entre
chamadas da mesma conversa e uma conversa não enxerga os arquivos da outra. Timeout = SIGINT; se o kernel não
voltar, é reiniciado (o estado se perde, e isso é dito na resposta).
"""
import base64
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

from jupyter_client import BlockingKernelClient
from jupyter_client.connect import write_connection_file

from . import workspace as ws

IDLE_MIN = int(os.environ.get("KERNEL_IDLE_MIN", "45"))
MAX_KERNELS = int(os.environ.get("MAX_KERNELS", "24"))
OUTPUT_LIMIT = 12000
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

STARTUP = r"""
import warnings; warnings.filterwarnings("ignore")
import os, json, math, re, datetime as dt
import numpy as np, pandas as pd, duckdb
import matplotlib
import matplotlib.pyplot as plt
get_ipython().run_line_magic("matplotlib", "inline")
pd.set_option("display.max_columns", 50); pd.set_option("display.width", 200); pd.set_option("display.max_rows", 60)
plt.rcParams.update({"figure.figsize": (9, 5), "figure.dpi": 110, "axes.grid": True, "grid.alpha": .3})
con = duckdb.connect()
"""


class Kernel:
    def __init__(self, sid: str):
        self.sid = sid
        self.lock = threading.Lock()
        self.last_used = time.time()
        self.figures = 0
        self._start()

    def _start(self):
        home = ws.workspace(self.sid)
        uid = ws.session_uid(self.sid)
        conn = home / ".kernel.json"
        write_connection_file(str(conn), ip="127.0.0.1")
        ws.fix_owner(self.sid, conn)
        conn.chmod(0o600)
        env = {"HOME": str(home), "PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1",
               "MPLCONFIGDIR": str(home / ".mpl"), "IPYTHONDIR": str(home / ".ipython"),
               "JUPYTER_RUNTIME_DIR": str(home / ".jupyter"), "MPLBACKEND": "module://matplotlib_inline.backend_inline",
               "LANG": "C.UTF-8", "PYTHONPATH": "/srv"}
        cmd = [sys.executable, "-m", "ipykernel_launcher", "-f", str(conn)]
        if os.geteuid() == 0:
            cmd = ["setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups", "--no-new-privs", *cmd]
        self.proc = subprocess.Popen(cmd, cwd=str(home), env=env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        self.client = BlockingKernelClient()
        self.client.load_connection_file(str(conn))
        self.client.start_channels()
        self.client.wait_for_ready(timeout=60)
        self._run(STARTUP, 60)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self):
        try:
            self.client.stop_channels()
        finally:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def restart(self):
        self.stop()
        self._start()

    def _run(self, code: str, timeout: float) -> dict:
        msg_id = self.client.execute(code, store_history=True, allow_stdin=False)
        out, images, error, result = [], [], None, None
        deadline = time.time() + timeout
        timed_out = False
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 and not timed_out:
                timed_out = True
                os.killpg(self.proc.pid, signal.SIGINT)
                deadline = time.time() + 8
                continue
            if remaining <= 0 and timed_out:
                self.restart()
                return {"stdout": "".join(out), "error": f"Tempo esgotado ({timeout:.0f}s). O kernel foi reiniciado "
                        "e as variáveis se perderam — reexecute o carregamento dos dados.", "images": images,
                        "result": None}
            try:
                msg = self.client.get_iopub_msg(timeout=min(1.0, max(remaining, 0.1)))
            except Exception:
                if not self.alive():
                    self._start()
                    return {"stdout": "".join(out), "error": "O kernel morreu (provável falta de memória) e foi "
                            "reiniciado; as variáveis se perderam.", "images": images, "result": None}
                continue
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            t, c = msg["msg_type"], msg["content"]
            if t == "stream":
                out.append(c.get("text", ""))
            elif t in ("execute_result", "display_data"):
                data = c.get("data", {})
                if "image/png" in data:
                    images.append(data["image/png"])
                elif "text/plain" in data:
                    if t == "execute_result":
                        result = data["text/plain"]
                    else:
                        out.append(data["text/plain"] + "\n")
            elif t == "error":
                error = ANSI.sub("", "\n".join(c.get("traceback", [])))[-4000:]
            elif t == "status" and c.get("execution_state") == "idle":
                break
        if timed_out:
            error = (error or "") + f"\nInterrompido após {timeout:.0f}s (KeyboardInterrupt); o estado foi mantido."
        return {"stdout": "".join(out), "result": result, "error": error, "images": images}

    def execute(self, code: str, timeout: float) -> dict:
        with self.lock:
            self.last_used = time.time()
            r = self._run(code, timeout)
            saved = []
            for png in r.pop("images"):
                self.figures += 1
                p = ws.unique_path(self.sid, f"figura_{self.figures}.png")
                p.write_bytes(base64.b64decode(png))
                ws.fix_owner(self.sid, p)
                saved.append(p.name)
            r["figures"] = saved
            for k in ("stdout", "result"):
                if r.get(k) and len(r[k]) > OUTPUT_LIMIT:
                    r[k] = r[k][:OUTPUT_LIMIT] + f"\n… [saída truncada: {len(r[k])} caracteres]"
            self.last_used = time.time()
            return r


_kernels: dict[str, Kernel] = {}
_glock = threading.Lock()


def get(sid: str) -> Kernel:
    with _glock:
        k = _kernels.get(sid)
        if k and not k.alive():
            k.stop()
            k = None
        if not k:
            if len(_kernels) >= MAX_KERNELS:
                oldest = min(_kernels.values(), key=lambda x: x.last_used)
                oldest.stop()
                _kernels.pop(oldest.sid, None)
            k = _kernels[sid] = Kernel(sid)
        return k


def reset(sid: str):
    with _glock:
        k = _kernels.pop(sid, None)
    if k:
        k.stop()


def _reaper():
    while True:
        time.sleep(60)
        now = time.time()
        with _glock:
            idle = [s for s, k in _kernels.items() if now - k.last_used > IDLE_MIN * 60]
            for s in idle:
                _kernels.pop(s).stop()


threading.Thread(target=_reaper, daemon=True).start()


def status() -> dict:
    return {"kernels": len(_kernels), "sessions": json.dumps(sorted(_kernels))[:200]}
