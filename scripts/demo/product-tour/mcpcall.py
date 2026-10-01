"""Cliente MCP da demo: chama uma ferramenta do MCP do Hangar como a Maya (o papel do Claude) e registra a chamada em transcript.jsonl.
Uso: python mcpcall.py list | python mcpcall.py call <tool> '<json args>'"""
import asyncio
import json
import os
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("HANGAR_MCP", "http://central:8080/mcp")
TOKEN = open("/demo/maya_token.txt").read().strip()
LOG = "/demo/transcript.jsonl"


async def main():
    async with streamablehttp_client(URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=900, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            if sys.argv[1] == "list":
                print("INSTRUCTIONS:", (init.instructions or "")[:200], "...")
                for t in (await s.list_tools()).tools:
                    print("-", t.name, "|", json.dumps(list((t.inputSchema.get("properties") or {}).keys())))
                return
            tool, args = sys.argv[2], json.loads(sys.argv[3] if len(sys.argv) > 3 else "{}")
            t0 = time.time()
            res = await s.call_tool(tool, args)
            text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
            out = {"tool": tool, "args": args, "result": text, "is_error": res.isError, "secs": round(time.time() - t0, 1)}
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
            print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])


asyncio.run(main())
