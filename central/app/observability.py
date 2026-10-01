"""Observabilidade da central: métricas Prometheus, logs em JSON e traces OpenTelemetry (opcionais).

- Métricas: cada réplica expõe as suas em `:METRICS_PORT/metrics` (porta separada, fora do Ingress; padrão desligado,
  o chart Helm liga na 9100) e, para quem não tem Prometheus, em `GET /api/metrics` (admins e auditores).
- Logs: `LOG_FORMAT=json` troca o texto por uma linha JSON por evento (Loki, Cloud Logging, CloudWatch, Azure Monitor).
- Traces: com `OTEL_EXPORTER_OTLP_ENDPOINT`, as requisições da central e as chamadas HTTP que ela faz (agentes, LLMs,
  MCPs) viram spans OTLP; o cabeçalho `traceparent` segue para os agentes. Funciona com Jaeger, Tempo, Langfuse,
  Datadog, Honeycomb, Grafana Cloud, Azure Monitor, Cloud Trace e X-Ray (via collector).
"""
import json
import logging
import time

from . import config

log = logging.getLogger("hangar.observability")

try:  # prometheus_client vem no requirements; sem ele, as métricas viram no-op
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest, start_http_server
    ENABLED = True
except ImportError:  # pragma: no cover
    ENABLED = False

if ENABLED:
    HTTP_REQUESTS = Counter("hangar_http_requests_total", "Requisições HTTP atendidas pela central",
                            ["method", "route", "status"])
    HTTP_SECONDS = Histogram("hangar_http_request_duration_seconds", "Duração das requisições HTTP", ["method", "route"],
                             buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120))
    INVOCATIONS = Counter("hangar_agent_invocations_total", "Chamadas a agentes (gateway, MCP, jobs, agendamentos)",
                          ["agent", "env", "channel", "protocol", "ok"])
    INVOCATION_SECONDS = Histogram("hangar_agent_invocation_duration_seconds", "Latência das chamadas a agentes",
                                   ["agent", "env"], buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 900))
    TOKENS = Counter("hangar_llm_tokens_total", "Tokens de LLM consumidos pelos agentes", ["agent", "env", "direction"])
    COST = Counter("hangar_llm_cost_usd_total", "Custo estimado de LLM em USD", ["agent", "env"])
    JOBS = Counter("hangar_jobs_finished_total", "Jobs de harness finalizados", ["status"])
    INFO = Gauge("hangar_build_info", "Versão e réplica da central", ["version", "replica", "runtime"])


def _route(scope) -> str:
    """Rota declarada (/api/agents/{slug}), nunca o caminho cru: mantém a cardinalidade das métricas baixa."""
    path = getattr(scope.get("route"), "path", "") or ""
    if path:
        return path
    p = scope.get("path", "")
    for prefix in ("/mcp", "/gw-stage/", "/gw/", "/ui", "/app", "/scim", "/.well-known", "/downloads", "/internal"):
        if p.startswith(prefix):
            return prefix.rstrip("/") + ("/{slug}" if prefix.startswith("/gw") else "")
    return path or "other"


class MetricsMiddleware:
    """ASGI: conta e mede cada requisição HTTP (rótulo = rota declarada)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not ENABLED:
            return await self.app(scope, receive, send)
        t0, status = time.perf_counter(), {"code": 500}

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        finally:
            route = _route(scope)
            HTTP_REQUESTS.labels(scope["method"], route, str(status["code"])).inc()
            HTTP_SECONDS.labels(scope["method"], route).observe(time.perf_counter() - t0)


def record_invocation(agent: str, env: str, channel: str, protocol: str, ok: bool, latency_ms: int,
                      tokens_in: int, tokens_out: int, cost: float):
    if not ENABLED:
        return
    INVOCATIONS.labels(agent, env, channel, protocol, "true" if ok else "false").inc()
    INVOCATION_SECONDS.labels(agent, env).observe(max(latency_ms, 0) / 1000)
    if tokens_in:
        TOKENS.labels(agent, env, "in").inc(tokens_in)
    if tokens_out:
        TOKENS.labels(agent, env, "out").inc(tokens_out)
    if cost:
        COST.labels(agent, env).inc(cost)


def record_job(status: str):
    if ENABLED:
        JOBS.labels(status).inc()


def metrics_text() -> tuple[bytes, str]:
    if not ENABLED:
        return b"# prometheus_client ausente\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST


def start_metrics_server():
    if not ENABLED:
        return
    INFO.labels(config.VERSION, config.REPLICA_ID, config.RUNTIME_BACKEND).set(1)
    if config.METRICS_PORT:
        try:
            start_http_server(config.METRICS_PORT)
            log.info("métricas Prometheus em :%s/metrics", config.METRICS_PORT)
        except OSError as e:  # porta ocupada (ex.: outro worker): segue sem o servidor dedicado
            log.warning("não foi possível abrir a porta de métricas %s: %s", config.METRICS_PORT, e)


# ------------------------------------------------------------------ logs em JSON
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
               "level": record.levelname.lower(), "logger": record.name, "msg": record.getMessage(),
               "replica": config.REPLICA_ID}
        span = _current_span_ids()
        if span:
            out.update(span)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging():
    root = logging.getLogger()
    if config.LOG_FORMAT == "json":
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        root.handlers[:] = [h]
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(name)
            lg.handlers[:] = []
            lg.propagate = True
    root.setLevel(config.LOG_LEVEL)


# ------------------------------------------------------------------ OpenTelemetry (opcional)
_tracing = False


def _current_span_ids() -> dict:
    if not _tracing:
        return {}
    from opentelemetry import trace
    ctx = trace.get_current_span().get_span_context()
    return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")} if ctx.is_valid else {}


def setup_tracing(app):
    """Liga os traces quando OTEL_EXPORTER_OTLP_ENDPOINT está definido (variáveis OTEL_* padrão)."""
    global _tracing
    if not config.OTEL_ENDPOINT:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT definido, mas os pacotes opentelemetry não estão instalados")
        return
    res = Resource.create({"service.name": config.OTEL_SERVICE_NAME, "service.version": config.VERSION,
                           "service.instance.id": config.REPLICA_ID})
    provider = TracerProvider(resource=res)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # endpoint/headers pelas variáveis OTEL_*
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="api/health,ui/.*,app/.*")
    HTTPXClientInstrumentor().instrument()
    _tracing = True
    log.info("traces OpenTelemetry ligados (%s)", config.OTEL_ENDPOINT)
