"""Retenção de workspaces (rode dentro da imagem):
    docker run --rm -v "$PWD/mcp-servers/data-studio/tests:/t" agent-hangar/mcp-data-studio python /t/test_retention.py
"""
import os
import tempfile
import time

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["RETENTION_DAYS"] = "1"

from app import workspace as ws  # noqa: E402

old, new = ws.session_id("conversa-antiga"), ws.session_id("conversa-nova")
for sid in (old, new):
    ws.touch(sid)
    (ws.workspace(sid) / "dados.csv").write_text("a\n1\n")
past = time.time() - 3 * 86400
os.utime(ws.workspace(old) / ".last_used", (past, past))
assert ws.expired() == [old], ws.expired()
ws.purge(old)
assert not (ws.SESSIONS / old).exists() and (ws.SESSIONS / new / "dados.csv").exists()
ws.touch(new)  # uso recente mantém
assert ws.expired() == []
print("retention ok")
