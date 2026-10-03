#!/usr/bin/env sh
# Regressão do Kubernetes: lá o /workspace (emptyDir) pertence ao root, não ao usuário do harness. O job tem de
# produzir o diff mesmo assim (antes o git recusava o repositório por "dubious ownership").
#   sh harness/tests/workspace_owner_check.sh agent-hangar/harness-base:latest
set -eu
IMAGE="$1"
OUT=$(docker run --rm --user 10001 --tmpfs /workspace:mode=1777,uid=0 -e HARNESS_ID=claude-code -e TASK=check \
  -e JOB_CALLBACK_URL=http://127.0.0.1:9999/cb --entrypoint sh "$IMAGE" -c '
python3 -c "
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(s):
        b = json.loads(s.rfile.read(int(s.headers[\"Content-Length\"])))
        print(\"DIFF:\" + b[\"diff\"][:200].replace(chr(10), \" \"))
        s.send_response(200); s.end_headers()
    def log_message(s, *a): pass
http.server.HTTPServer((\"127.0.0.1\", 9999), H).handle_request()" &
sleep 1; node /srv/entrypoint.js >/dev/null 2>&1; wait')
echo "$OUT"
case "$OUT" in
  *"DIFF:diff --git"*) echo "ok: diff do job com o workspace de outro dono" ;;
  *) echo "FAIL: o job não gerou o diff"; exit 1 ;;
esac
