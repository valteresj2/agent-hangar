"""Alvo Kubernetes do `hangar setup` (GKE, AKS, EKS ou qualquer cluster): gera os values do chart Helm a partir das
respostas, instala com `helm upgrade --install` e configura pela API através de um port-forward temporário.

Arquivos gerados em .hangar/:
- values.yaml          escolhas sem segredo (versionável, se quiser);
- secrets.values.yaml  segredos (permissão 600, git-ignorado). Gerados uma vez e reaproveitados nos upgrades —
                       nunca troque o secretKey depois de instalar (ele decifra as chaves de LLM no banco).
"""
import base64
import contextlib
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import yaml

PROVIDERS = {"gke": "Google GKE", "aks": "Azure AKS", "eks": "Amazon EKS", "local": "Outro / local (k3s, kind, Docker Desktop…)"}
EXPOSURES = {"ingress": "Ingress com TLS (load balancer do cluster)", "cloudflare": "Cloudflare Tunnel (sem load balancer)",
             "portforward": "Sem exposição (kubectl port-forward, para testar)"}


def fullname(release: str) -> str:
    """Mesma regra do _helpers.tpl do chart."""
    name = release if "agent-hangar" in release else f"{release}-agent-hangar"
    return name[:40].rstrip("-")


def public_url(k: dict) -> str:
    exp = k.get("exposure", "portforward")
    if exp == "ingress":
        return f"https://{k['host']}"
    if exp == "cloudflare":
        return f"https://{k['hostname']}"
    return f"http://localhost:{k.get('local_port', 18090)}"


def build_values(a: dict, version: str) -> tuple[dict, dict]:
    """(values sem segredo, values com segredos) a partir das respostas validadas."""
    k = a["kubernetes"]
    v: dict = {"publicUrl": public_url(k), "image": {"registry": k.get("registry", "ghcr.io/valteresj2"),
                                                       "tag": k.get("tag") or version}}
    s: dict = {}
    exp = k.get("exposure", "portforward")
    if exp == "ingress":
        ing: dict = {"enabled": True, "host": k["host"]}
        if k.get("issuer"):
            ing["annotations"] = {"cert-manager.io/cluster-issuer": k["issuer"]}
        v["ingress"] = ing
    else:
        v["ingress"] = {"enabled": False}
    if exp == "cloudflare":
        v["tunnel"] = {"cloudflare": {"enabled": True}}
        s["tunnel"] = {"cloudflare": {"token": k["token"]}}
    db = k.get("database", "bundled")
    if db == "external":
        v["postgresql"] = {"enabled": False}
        s["postgresql"] = {"external": {"url": k["database_url"]}}
    mem = a.get("memory", "none")
    if mem in ("neo4j", "falkordb"):
        v["memory"] = {"enabled": True, "backend": mem, "llmConnection": (a.get("llm") or {}).get("name", "")}
    sso = a.get("sso") or {"provider": "none"}
    prov = sso.get("provider", "none")
    v["sso"] = {"localLogin": True, "bootstrapAdminEmails": a.get("admin", {}).get("email", "")}
    if prov != "none":
        pub = {"clientId": sso.get("client_id", "")}
        for src, dst in (("tenant", "tenant"), ("allowed_domains", "allowedDomains"), ("label", "label"),
                         ("authorize_url", "authorizeUrl"), ("token_url", "tokenUrl"), ("userinfo_url", "userinfoUrl")):
            if sso.get(src):
                pub[dst] = sso[src]
        v["sso"][prov] = pub
        s["sso"] = {prov: {"clientSecret": sso.get("client_secret", "")}}
    v["networkPolicy"] = {"enabled": True, "allowPrivateEgress": bool(k.get("allow_private_egress"))}
    return v, s


def merge_secrets(new: dict, old: dict) -> dict:
    """Segredos novos + os gerados antes (nunca troca adminToken/secretKey/internalSecret/senhas já existentes)."""
    out = dict(old or {})
    base = out.setdefault("secrets", {})
    for key, gen in (("adminToken", lambda: secrets.token_hex(32)), ("internalSecret", lambda: secrets.token_hex(32)),
                     ("secretKey", lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())):
        base.setdefault(key, gen())
    pg = out.setdefault("postgresql", {})
    pg.setdefault("password", secrets.token_hex(24))
    for top, val in new.items():  # tokens de túnel, banco externo e SSO: o informado agora vence
        if isinstance(val, dict):
            cur = out.setdefault(top, {})
            for k2, v2 in val.items():
                cur[k2] = {**cur.get(k2, {}), **v2} if isinstance(v2, dict) else v2
        else:
            out[top] = val
    return out


def write_values(state: Path, values: dict, secret_values: dict) -> tuple[Path, Path]:
    vp, sp = state / "values.yaml", state / "secrets.values.yaml"
    vp.write_text("# gerado pelo hangar setup (alvo kubernetes)\n" + yaml.safe_dump(values, sort_keys=False, allow_unicode=True),
                  encoding="utf-8")
    sp.write_text("# SEGREDOS — não versione, não compartilhe. Gerado pelo hangar setup.\n"
                  + yaml.safe_dump(secret_values, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        sp.chmod(0o600)
    except OSError:
        pass
    return vp, sp


def helm_command(root: Path, a: dict, vp: Path, sp: Path) -> list[str]:
    k = a["kubernetes"]
    chart = root / "charts" / "agent-hangar"
    cmd = ["helm", "upgrade", "--install", k.get("release", "agent-hangar"), str(chart), "-n", k.get("namespace", "agent-hangar"),
           "--create-namespace"]
    preset = chart / f"values-{k.get('provider', 'local')}.yaml"
    if preset.exists():
        cmd += ["-f", str(preset)]
    return cmd + ["-f", str(vp), "-f", str(sp), "--wait", "--timeout", "10m"]


def preflight() -> list[str]:
    problems = []
    for tool, hint in (("kubectl", "https://kubernetes.io/docs/tasks/tools/"), ("helm", "https://helm.sh/docs/intro/install/")):
        if not shutil.which(tool):
            problems.append(f"{tool} não encontrado ({hint})")
    if not problems:
        r = subprocess.run(["kubectl", "version", "--request-timeout=10s"], capture_output=True, text=True)
        if r.returncode != 0:
            problems.append("kubectl não alcança o cluster: confira o contexto (kubectl config current-context) e as credenciais")
    return problems


def current_context() -> str:
    r = subprocess.run(["kubectl", "config", "current-context"], capture_output=True, text=True)
    return r.stdout.strip() or "(nenhum)"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def port_forward(namespace: str, release: str, timeout: int = 60):
    """http://localhost:<porta> -> svc/<release>-central:8080 enquanto o bloco roda."""
    port = free_port()
    proc = subprocess.Popen(["kubectl", "-n", namespace, "port-forward", f"svc/{fullname(release)}-central", f"{port}:8080"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://localhost:{port}"
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/api/health", timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        else:
            raise RuntimeError("port-forward para a central não respondeu")
        yield base
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(5)


def admin_token_from_cluster(namespace: str, release: str) -> str:
    r = subprocess.run(["kubectl", "-n", namespace, "get", "secret", f"{fullname(release)}-secrets",
                        "-o", "jsonpath={.data.ADMIN_TOKEN}"], capture_output=True, text=True)
    return base64.b64decode(r.stdout).decode() if r.returncode == 0 and r.stdout else ""


def pods_summary(namespace: str, release: str) -> tuple[list[str], list[str]]:
    """(pods ok, pods com problema) da instalação e dos agentes no namespace."""
    r = subprocess.run(["kubectl", "-n", namespace, "get", "pods", "-o",
                        "jsonpath={range .items[*]}{.metadata.name}|{.status.phase}|{.status.containerStatuses[0].ready}|"
                        "{.status.containerStatuses[0].state.waiting.reason}{'\\n'}{end}"], capture_output=True, text=True)
    good, bad = [], []
    for line in r.stdout.splitlines():
        name, phase, ready, reason = (line.split("|") + ["", "", "", ""])[:4]
        if phase == "Succeeded":
            continue
        (good if phase == "Running" and ready == "true" else bad).append(f"{name} ({reason or phase})" if not (phase == "Running" and ready == "true") else name)
    return good, bad
