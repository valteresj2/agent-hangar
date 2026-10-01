"""Observabilidade: métricas Prometheus (HTTP por rota declarada, chamadas a agentes, tokens, custo, jobs), acesso a
/api/metrics só para admins e auditores, logs em JSON e traces OpenTelemetry com exportador em memória."""
import json
import logging

from app import config, observability
from app import services as svc

from .conftest import ADMIN
from .test_jobs import _harness_agent


def _value(text: str, name: str, **labels) -> float:
    for line in text.splitlines():
        if line.startswith(name + "{") and all(f'{k}="{v}"' in line for k, v in labels.items()):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def test_metrics_endpoint_and_http_labels(client):
    assert client.get("/api/metrics").status_code == 401
    client.get("/api/agents", headers=ADMIN)
    client.get("/gw/nao-existe/v1/models", headers=ADMIN)
    r = client.get("/api/metrics", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    t = r.text
    assert _value(t, "hangar_http_requests_total", method="GET", route="/api/agents", status="200") >= 1
    assert 'route="/gw/nao-existe' not in t  # caminho cru nunca vira rótulo
    assert "hangar_http_request_duration_seconds_bucket" in t


def test_invocations_tokens_cost_and_jobs(client, db, uniq, fake_docker):
    conn = uniq("anthropic")
    svc.upsert_llm_connection(db, conn, "https://api.anthropic.com", "claude-x", "sk", "", "t", "anthropic", 3.0, 15.0)
    a = _harness_agent(db, uniq, conn)
    before = observability.metrics_text()[0].decode()
    job = svc.run_harness_job(db, a.slug, "x", "stage", 30, "t", "api")
    after = observability.metrics_text()[0].decode()
    assert _value(after, "hangar_agent_invocations_total", agent=a.slug, env="stage", protocol="harness-job", ok="true") == 1
    assert _value(after, "hangar_llm_tokens_total", agent=a.slug, direction="in") == 1000
    assert _value(after, "hangar_llm_cost_usd_total", agent=a.slug) == job.cost_usd
    assert _value(after, "hangar_jobs_finished_total", status="passed") == \
        _value(before, "hangar_jobs_finished_total", status="passed") + 1


def test_json_logs(monkeypatch):
    rec = logging.LogRecord("hangar.x", logging.WARNING, __file__, 1, "olá %s", ("mundo",), None)
    out = json.loads(observability.JsonFormatter().format(rec))
    assert out["msg"] == "olá mundo" and out["level"] == "warning" and out["replica"] == config.REPLICA_ID


def test_tracing_spans_for_requests(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    app = FastAPI()

    @app.get("/api/ping/{x}")
    def ping(x: str):
        return {"x": x}
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    TestClient(app).get("/api/ping/1")
    assert any(s.name.startswith("GET /api/ping/{x}") for s in exporter.get_finished_spans())
    # sem endpoint configurado, setup_tracing não liga nada
    monkeypatch.setattr(config, "OTEL_ENDPOINT", "")
    observability.setup_tracing(FastAPI())
    assert observability._current_span_ids() == {}
