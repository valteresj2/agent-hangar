"""Maya conversa com um agente em produção pelo gateway OpenAI-compatible (uso registrado como dela).
Uso: python chat.py <slug> "<mensagem>" [sessão]"""
import json
import sys
import time

import httpx

TOKEN = open("/demo/maya_token.txt").read().strip()
slug, msg = sys.argv[1], sys.argv[2]
session = sys.argv[3] if len(sys.argv) > 3 else f"demo-maya-{slug}"
t0 = time.time()
r = httpx.post(f"http://central:8080/gw/{slug}/v1/chat/completions", timeout=600,
               headers={"Authorization": f"Bearer {TOKEN}", "X-Session-Id": session},
               json={"model": slug, "messages": [{"role": "user", "content": msg}]})
r.raise_for_status()
reply = r.json()["choices"][0]["message"]["content"]
with open("/demo/chats.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"agent": slug, "user": msg, "assistant": reply, "secs": round(time.time() - t0, 1)}, ensure_ascii=False) + "\n")
print(reply)
