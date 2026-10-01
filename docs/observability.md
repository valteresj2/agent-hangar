# Observability

The central exposes Prometheus metrics, can write JSON logs, and can send OpenTelemetry traces. All three work with
Docker and Kubernetes, and each replica reports its own data (Prometheus sums them).

## Metrics (Prometheus)

| Metric | Labels | What |
|---|---|---|
| `hangar_agent_invocations_total` | `agent`, `env`, `channel`, `protocol`, `ok` | Calls to agents: gateway, MCP, jobs, schedules, tests |
| `hangar_agent_invocation_duration_seconds` | `agent`, `env` | Agent latency (histogram) |
| `hangar_llm_tokens_total` | `agent`, `env`, `direction` (`in`/`out`) | LLM tokens |
| `hangar_llm_cost_usd_total` | `agent`, `env` | Estimated LLM cost in USD (catalog prices) |
| `hangar_jobs_finished_total` | `status` | Harness jobs by final status |
| `hangar_http_requests_total` | `method`, `route`, `status` | HTTP requests; `route` is the declared route (`/api/agents/{slug}`), never the raw path |
| `hangar_http_request_duration_seconds` | `method`, `route` | HTTP latency (histogram) |
| `hangar_build_info` | `version`, `replica`, `runtime` | One series per replica |

Where to read them:
- **Kubernetes:** each pod serves `:9100/metrics` (`observability.metrics`). The port is on the Service but not on the
  Ingress. With the Prometheus Operator, set `observability.serviceMonitor.enabled=true`. On GKE Managed Prometheus,
  create a `PodMonitoring` for port `metrics`.
- **Docker:** set `METRICS_PORT=9100` in `.env` and scrape `central:9100` from a Prometheus on the same network.
  Without Prometheus, `GET /api/metrics` returns the same text to admins and auditors.

### Grafana

`observability.grafanaDashboard.enabled=true` creates a ConfigMap labeled `grafana_dashboard: "1"`; the Grafana
sidecar (kube-prometheus-stack) imports it. The dashboard shows replicas, calls, error rate, cost and tokens in the
last 24 hours, API p95, plus calls, latency, cost and tokens per agent, HTTP status and harness jobs. To import it by
hand, use [`charts/agent-hangar/dashboards/agent-hangar.json`](../charts/agent-hangar/dashboards/agent-hangar.json).

Useful alerts:

```yaml
- alert: HangarAgentErrors
  expr: sum by (agent) (rate(hangar_agent_invocations_total{ok="false"}[10m]))
        / sum by (agent) (rate(hangar_agent_invocations_total[10m])) > 0.2
  for: 10m
- alert: HangarCostSpike
  expr: sum(increase(hangar_llm_cost_usd_total[1h])) > 50
- alert: HangarNoReplicas
  expr: absent(hangar_build_info)
  for: 5m
```

## Logs

`LOG_FORMAT=json` (the chart default) writes one JSON object per line: `ts`, `level`, `logger`, `msg`, `replica`,
and `trace_id`/`span_id` when tracing is on. Cloud Logging, CloudWatch, Azure Monitor, Loki and Datadog parse it
without extra configuration. `LOG_LEVEL` sets the level (default `INFO`).

## Traces (OpenTelemetry)

Set the standard OpenTelemetry variables and the central starts sending traces over OTLP/HTTP:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
# optional: OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer …, OTEL_TRACES_SAMPLER=parentbased_traceidratio, OTEL_TRACES_SAMPLER_ARG=0.2
```

In the chart, use `observability.otlp.endpoint` and `observability.otlp.sampleRatio`.
- Every request to the central is a span.
- So is every HTTP call it makes: agents, LLMs, MCPs.
- The `traceparent` header follows the call to the agents.

Send the traces to an OpenTelemetry Collector and from there to Tempo, Jaeger, Langfuse, Datadog, Honeycomb, Grafana
Cloud, Cloud Trace, X-Ray or Azure Monitor.
