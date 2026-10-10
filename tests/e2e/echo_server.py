"""Sistema de mentira para os testes ponta a ponta dos plugins: devolve em JSON o que recebeu (método, caminho,
cabeçalhos, corpo). /status/<código> responde com aquele código. Só a biblioteca padrão."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Echo(BaseHTTPRequestHandler):
    def _reply(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n).decode(errors="replace") if n else ""
        out = json.dumps({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}).encode()
        code = int(self.path.split("/status/", 1)[1].split("?")[0]) if "/status/" in self.path else 200
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _reply

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Echo).serve_forever()
