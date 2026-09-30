"""Ana conversa com o Assistente Comercial em produção pelo gateway OpenAI-compatible (uso registrado como dela)."""
import json
import sys
import time

import httpx

TOKEN = open("/demo/ana_token.txt").read().strip()
msg, session = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "demo-ana")
t0 = time.time()
r = httpx.post("http://central:8080/gw/assistente-comercial/v1/chat/completions", timeout=300,
               headers={"Authorization": f"Bearer {TOKEN}", "X-Session-Id": session, "X-Channel": "claude-demo"},
               json={"model": "assistente-comercial", "messages": [{"role": "user", "content": msg}]})
r.raise_for_status()
reply = r.json()["choices"][0]["message"]["content"]
with open("/demo/chats.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"user": msg, "assistant": reply, "secs": round(time.time() - t0, 1)}, ensure_ascii=False) + "\n")
print(reply)
