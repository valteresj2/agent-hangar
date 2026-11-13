"""Roda os casos do desktop governado no Cua Bench, contra uma instalação com o perfil desktop no ar.

    # só a solução de referência: prova que cada evaluate aceita o estado certo e recusa o desktop sem nada feito
    python tests/bench/desktop/run.py --oracle

    # o Digital employee de verdade, com um modelo de verdade (cria e apaga um time, duas pessoas e o funcionário)
    HANGAR_URL=http://localhost:8090 HANGAR_TOKEN=<admin> LLM_CONNECTION=openrouter-deepseek \
      python tests/bench/desktop/run.py [caso ...] [--attempts 3] [--keep]

O runner (Dockerfile ao lado) entra na rede do desktop, que não tem saída para a internet: fala com o cua-spacesd do
desktop para preparar e conferir o estado, e com a central, que dá a tarefa ao funcionário. O token da Cua é lido do
container e só vai para o runner por um arquivo de ambiente temporário, apagado no fim. Cada rodada sai em
tests/bench/desktop/out/<rodada>/: o summary.json e, por tentativa, os arquivos do Cua Bench e o resumo da tarefa na
central (hangar-task.json). Os passos e as capturas do funcionário ficam na linha do tempo da tarefa.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
IMAGE = os.environ.get("BENCH_IMAGE", "agent-hangar/desktop-bench:dev")
NETWORK = os.environ.get("BENCH_NETWORK", "hangar_desktop")
CENTRAL = os.environ.get("BENCH_CENTRAL_URL", "http://central:8080")  # a central vista de dentro da rede do desktop
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}  # Git Bash no Windows não reescreve /run/... e /out

# os ids das variantes, na ordem do main.py (o cua_bench só existe dentro do runner)
with open(os.path.join(HERE, "hangar_desktop", "main.py"), encoding="utf-8") as _fh:
    _src = _fh.read()
CASE_IDS = re.findall(r'^    \("([a-z-]+)", "', _src.split("CASES = [", 1)[1].split("\n]", 1)[0], re.M)


def sh(*cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=ENV, cwd=ROOT, **kw)


def build():
    r = sh("docker", "build", "-q", "-t", IMAGE, HERE)
    if r.returncode:
        raise SystemExit(f"build do runner: {r.stderr[-800:]}")


def token() -> str:
    r = sh("docker", "compose", "exec", "-T", "desktop", "cat", "/run/cua/env-token")
    if r.returncode or not r.stdout.strip():
        raise SystemExit("o desktop não está no ar (docker compose --profile desktop up -d desktop)")
    return r.stdout.strip()


def solve(index: int, out: str, extra: dict, mode: list[str]) -> float | None:
    """Uma variante no runner; devolve a nota do evaluate (None se o episódio não chegou a avaliar)."""
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as fh:
        fh.write(f"CUA_ENV_TOKEN={token()}\n" + "".join(f"{k}={v}\n" for k, v in extra.items()))
        env_file = fh.name
    try:
        os.makedirs(out, exist_ok=True)
        r = sh("docker", "run", "--rm", "--network", NETWORK, "--env-file", env_file,
               "-e", "CUA_ENV_API_URL=http://desktop:3211", "-v", f"{out}:/out", IMAGE,
               "hangar_desktop", "--task-index", str(index), *mode)
    finally:
        os.unlink(env_file)
    with open(os.path.join(out, "solver.log"), "w", encoding="utf-8") as fh:
        fh.write(r.stdout + r.stderr)
    m = re.search(r"Evaluation result: \[([\d.]+)", r.stdout + r.stderr)
    return float(m.group(1)) if m else None


def oracle(run_dir: str) -> bool:
    good = True
    for i, cid in enumerate(CASE_IDS):
        right = solve(i, os.path.join(run_dir, cid, "oracle"), {}, [])
        empty = solve(i, os.path.join(run_dir, cid, "empty"), {}, ["--dump"])  # preparar e avaliar, sem fazer nada
        ok_ = right == 1.0 and empty == 0.0
        good &= ok_
        print(f"{'ok  ' if ok_ else 'FALHA'} {cid}: referência={right} sem fazer nada={empty}", flush=True)
    return good


def with_employee(run_dir: str, only: list[str], attempts: int, keep: bool) -> bool:
    sys.path.insert(0, os.path.join(ROOT, "tests", "e2e"))
    import pilot_llm as pl  # o mesmo funcionário dos testes com LLM de verdade
    import workforce as wf
    ok, admin = wf.ok, wf.admin
    secret = f"erp-bench-{wf.RUN}"
    password = os.environ.get("ERP_TEST_PASSWORD", "erp-teste-123")
    leftovers = []
    summary = {"run": os.path.basename(run_dir), "connection": pl.CONN, "attempts": attempts, "cases": {}}
    try:
        team = ok(admin.post("/api/teams", json={"name": f"Bench desktop {wf.RUN}"}))["slug"]
        wf.created["team"] = team
        _, mgr_email, mgr_key = wf.person("mgr", "maintainer", team)
        dev, _, dev_key = wf.person("dev", "developer", team)
        mgr = wf.httpx.Client(base_url=wf.URL, timeout=300, headers={"Authorization": f"Bearer {mgr_key}"})
        slug = pl.hire(dev, mgr_email, team)
        ok(mgr.put(f"/api/employees/{slug}/desktop-apps", json={"apps": ["ERP Legado", "Gnumeric"]}))
        wf.activate(dev, mgr, slug)
        ok(admin.put("/api/secrets", json={"name": secret, "value": password}))
        leftovers.append(next(s["id"] for s in ok(admin.get("/api/secrets"))["secrets"] if s["name"] == secret))
        extra = {"HANGAR_URL": CENTRAL, "HANGAR_EMPLOYEE": slug, "HANGAR_DEV_KEY": dev_key, "HANGAR_MGR_KEY": mgr_key,
                 "HANGAR_SECRET": secret, "ERP_TEST_PASSWORD": password}
        for i, cid in enumerate(CASE_IDS):
            if only and cid not in only:
                continue
            rewards = []
            for a in range(attempts):
                out = os.path.join(run_dir, cid, f"attempt-{a + 1}")
                t0 = time.time()
                rewards.append(solve(i, out, extra, ["--eval", "--agent-import-path", "hangar_agent:HangarEmployee"]))
                task = _task_summary(out)
                print(f"{'ok  ' if rewards[-1] == 1.0 else 'FALHA'} {cid} #{a + 1}: nota={rewards[-1]} "
                      f"{time.time() - t0:.0f}s tarefa={task.get('task')} status={task.get('status')} "
                      f"aprovações={len(task.get('approvals', []))}", flush=True)
            summary["cases"][cid] = {"rewards": rewards, "pass_at_k": any(r == 1.0 for r in rewards),
                                     "pass_rate": sum(r == 1.0 for r in rewards) / len(rewards)}
    finally:
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)
        if keep:
            print("dados mantidos (--keep)", flush=True)
        else:
            for sid in leftovers:
                admin.delete(f"/api/secrets/{sid}")
            wf.cleanup()
    cases = summary["cases"].values()
    print(f"\n{sum(c['pass_at_k'] for c in cases)}/{len(summary['cases'])} casos (pass@{attempts}) com {pl.CONN}; "
          f"resultados em {run_dir}", flush=True)
    return bool(cases) and all(c["pass_at_k"] for c in cases)


def _task_summary(out: str) -> dict:
    for base, _, files in os.walk(out):
        if "hangar-task.json" in files:
            with open(os.path.join(base, "hangar-task.json"), encoding="utf-8") as fh:
                return json.load(fh)
    return {}


def main():
    args = sys.argv[1:]
    attempts = int(args[args.index("--attempts") + 1]) if "--attempts" in args else 1
    only = [a for a in args if not a.startswith("-") and a in CASE_IDS]
    run_dir = os.path.join(HERE, "out", time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4])
    build()
    good = oracle(run_dir) if "--oracle" in args else with_employee(run_dir, only, attempts, "--keep" in args)
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
