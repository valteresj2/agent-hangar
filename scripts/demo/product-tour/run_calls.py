"""Roda em sequência as chamadas MCP de calls.json como a Maya (o que o Claude faria), registrando tudo em
transcript.jsonl via mcpcall.py. Para na primeira chamada com erro."""
import json
import subprocess
import sys

calls = json.load(open("/demo/calls.json", encoding="utf-8"))
start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
for i, (tool, args) in enumerate(calls[start:], start=start):
    print(f"== {i} {tool}", flush=True)
    r = subprocess.run([sys.executable, "/demo/mcpcall.py", "call", tool, json.dumps(args)], capture_output=True, text=True)
    print(r.stdout[-1500:], r.stderr[-800:], flush=True)
    if r.returncode or '"is_error": true' in r.stdout:
        sys.exit(f"parou na chamada {i} ({tool})")
