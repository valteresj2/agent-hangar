"""Configuração do Agent Hangar — tudo vem de variáveis de ambiente (ver .env.example)."""
import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


APP_NAME = "Agent Hangar"
VERSION = "0.16.1"

DATABASE_URL = _env("DATABASE_URL", "sqlite:///./hangar.db")

# Token de bootstrap com poder total de administração. Depois do primeiro acesso, prefira chaves de API
# com escopo (aba "Chaves de API" / `hangar keys create`). Nunca é injetado em container de agente.
ADMIN_TOKEN = _env("ADMIN_TOKEN")

# Chave (Fernet, base64 de 32 bytes) que criptografa em repouso as api keys das conexões de LLM.
# Obrigatória: sem ela a central não sobe. Gere com: scripts/setup.sh (ou .ps1).
SECRET_KEY = _env("HANGAR_SECRET_KEY")

# Segredo HMAC dos tokens internos por agente (agente -> central). Cada container recebe só o token do
# próprio slug; a central confere quem está chamando e se o destino é mesmo um sub_agent dele.
INTERNAL_SECRET = _env("INTERNAL_SECRET") or _env("INTERNAL_TOKEN")

PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8090").rstrip("/")

# Login (OAuth2). Sessão da UI em cookie HttpOnly; e-mails desta lista viram admin da plataforma no login.
# Credenciais dos provedores: OAUTH_GOOGLE_*, OAUTH_MICROSOFT_*, OAUTH_GITHUB_*, OAUTH_OAUTH2_* (ver .env.example)
# ou na página "SSO e SCIM" da UI (o que for salvo lá tem prioridade).
SESSION_TTL_HOURS = int(_env("SESSION_TTL_HOURS", "12"))
BOOTSTRAP_ADMIN_EMAILS = {e.strip().lower() for e in _env("BOOTSTRAP_ADMIN_EMAILS").split(",") if e.strip()}
# Contas locais (usuário e senha). Empresas que exigem só SSO desligam com LOCAL_LOGIN=0.
LOCAL_LOGIN = _env("LOCAL_LOGIN", "1") == "1"
COOKIE_SECURE = _env("COOKIE_SECURE", "1" if PUBLIC_BASE_URL.startswith("https://") else "0") == "1"
INTERNAL_BASE_URL = _env("INTERNAL_BASE_URL", "http://central:8080").rstrip("/")
# Nome desta réplica da central (no Kubernetes, o nome do pod). Com várias réplicas, cada uma só recupera os
# próprios jobs órfãos ao reiniciar.
REPLICA_ID = (_env("REPLICA_ID") or _env("HOSTNAME") or "central")[:100]

# OAuth do MCP da plataforma (Claude.ai, ChatGPT e outros clientes web): o cliente se registra sozinho (RFC 7591),
# a pessoa entra pelo portal e autoriza; o app recebe um token curto + refresh. Redirects só para os hosts abaixo
# (separados por vírgula; "*" libera qualquer https). localhost/127.0.0.1 valem sempre (clientes locais).
OAUTH_ENABLED = _env("OAUTH_ENABLED", "1") == "1"
OAUTH_REDIRECT_HOSTS = [h.strip().lower() for h in _env(
    "OAUTH_REDIRECT_HOSTS", "claude.ai,claude.com,chatgpt.com,chat.openai.com,platform.openai.com").split(",") if h.strip()]
OAUTH_ACCESS_TTL_S = int(_env("OAUTH_ACCESS_TTL_S", "3600"))
OAUTH_REFRESH_TTL_DAYS = int(_env("OAUTH_REFRESH_TTL_DAYS", "30"))

# Imagens. HANGAR_REGISTRY=ghcr.io/<owner> usa as imagens publicadas; o padrão usa os builds locais.
REGISTRY = _env("HANGAR_REGISTRY", "agent-hangar").rstrip("/")
IMAGE_TAG = _env("HANGAR_VERSION", "latest")
RUNTIME_IMAGE = _env("RUNTIME_IMAGE", f"{REGISTRY}/agent-runtime:{IMAGE_TAG}")


def harness_image(harness_id: str) -> str:
    """Imagem do container de job. `base` roda o modo mock (sem nenhum CLI de harness instalado)."""
    override = _env(f"HARNESS_IMAGE_{harness_id.upper().replace('-', '_')}")
    return override or f"{REGISTRY}/harness-{harness_id}:{IMAGE_TAG}"


# Onde os agentes rodam: docker (containers via socket proxy) | kubernetes (Deployments/Jobs no namespace da central)
RUNTIME_BACKEND = _env("RUNTIME_BACKEND", "docker").lower()
K8S_NAMESPACE = _env("K8S_NAMESPACE")  # vazio = o namespace da própria central (ServiceAccount)
K8S_IMAGE_PULL_SECRET = _env("K8S_IMAGE_PULL_SECRET")  # registry privado: nome(s) do(s) Secret(s), separados por vírgula
K8S_PULL_POLICY = _env("K8S_PULL_POLICY", "IfNotPresent")

AGENTS_NETWORK = _env("AGENTS_NETWORK", "hangar_agents")
# Rede isolada dos jobs: alcançam a central (callback) e a internet (LLM/MCP), nunca os outros agentes.
JOBS_NETWORK = _env("JOBS_NETWORK", "hangar_jobs")

# Fallback quando o agente não tem LlmConnection (sem custo, sem chave — só para validar o fluxo).
DEFAULT_MODEL = _env("DEFAULT_MODEL", "mock/echo")
AGENT_MEM_LIMIT = _env("AGENT_MEM_LIMIT", "512m")
AGENT_CPUS = float(_env("AGENT_CPUS", "1.0"))

JOB_MEM_LIMIT = _env("JOB_MEM_LIMIT", "1g")
JOB_CPUS = float(_env("JOB_CPUS", "1.0"))
JOB_TIMEOUT_S = int(_env("JOB_TIMEOUT_S", "180"))
JOB_MAX_TIMEOUT_S = int(_env("JOB_MAX_TIMEOUT_S", "900"))
# rascunho do guia do agente gerado pelo LLM quando uma versão vai para produção sem guia escrito
GUIDE_AUTOGEN = _env("GUIDE_AUTOGEN", "1") == "1"
# Digital employee: tarefas rodando em paralelo por réplica, rodadas máximas por tarefa e prazo padrão das decisões
EMPLOYEE_WORKERS = int(_env("EMPLOYEE_WORKERS", "3"))
EMPLOYEE_MAX_RUNS = int(_env("EMPLOYEE_MAX_RUNS", "12"))
DECISION_EXPIRES_MIN = int(_env("DECISION_EXPIRES_MIN", "240"))
JOB_WORKERS = int(_env("JOB_WORKERS", "8"))

# Agendamentos (execuções de agentes em produção por cron ou data única)
SCHEDULER_ENABLED = _env("SCHEDULER_ENABLED", "1") == "1"
SCHEDULER_TICK_S = int(_env("SCHEDULER_TICK_S", "20"))
SCHEDULE_WORKERS = int(_env("SCHEDULE_WORKERS", "4"))
SCHEDULE_RUN_TIMEOUT_S = int(_env("SCHEDULE_RUN_TIMEOUT_S", "900"))
SCHEDULE_MIN_INTERVAL_MIN = int(_env("SCHEDULE_MIN_INTERVAL_MIN", "5"))
SCHEDULE_ALLOW_PRIVATE_WEBHOOKS = _env("SCHEDULE_ALLOW_PRIVATE_WEBHOOKS", "0") == "1"

# Catálogo Docker MCP (profile mcp-gateway): o gateway agrega servidores MCP prontos, cada um num container
MCP_GATEWAY_URL = _env("MCP_GATEWAY_URL", "http://mcp-gateway:8811/mcp")
MCP_GATEWAY_CONFIG_DIR = _env("MCP_GATEWAY_CONFIG_DIR", "")  # volume compartilhado com o gateway (vazio = só o banco)
MCP_GATEWAY_CATALOG_URL = _env("MCP_GATEWAY_CATALOG_URL", "https://desktop.docker.com/mcp/catalog/v2/catalog.yaml")
MCP_GATEWAY_CATALOG_TTL_S = int(_env("MCP_GATEWAY_CATALOG_TTL_S", "21600"))

# Memória dos agentes (profile memory): Graphiti sobre Neo4j/FalkorDB. Vazio = desligada.
MEMORY_URL = _env("MEMORY_URL", "").rstrip("/")
MEMORY_TOKEN = _env("MEMORY_TOKEN")  # só a central e o serviço de memória conhecem
MEMORY_LLM_CONNECTION = _env("MEMORY_LLM_CONNECTION")  # LlmConnection (protocol openai) que extrai os fatos
MEMORY_LLM_MODEL = _env("MEMORY_LLM_MODEL")  # vazio = o modelo padrão da conexão
MEMORY_LLM_OUTPUT_MODE = _env("MEMORY_LLM_OUTPUT_MODE", "json_object")  # json_schema para provedores que suportam
MEMORY_EMBEDDING_CONNECTION = _env("MEMORY_EMBEDDING_CONNECTION")  # só com MEMORY_EMBEDDER=openai no serviço
MEMORY_EMBEDDING_MODEL = _env("MEMORY_EMBEDDING_MODEL")

TEMPLATES_DIR =_env("TEMPLATES_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                  "templates"))

# Observabilidade (ver observability.py): métricas Prometheus numa porta separada (0 = desligada; o chart usa 9100),
# logs em JSON e traces OpenTelemetry (ligados pelas variáveis OTEL_* padrão, a começar por OTEL_EXPORTER_OTLP_ENDPOINT).
METRICS_PORT = int(_env("METRICS_PORT", "0") or 0)
LOG_FORMAT = _env("LOG_FORMAT", "text").lower()
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
OTEL_ENDPOINT = _env("OTEL_EXPORTER_OTLP_ENDPOINT") or _env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
OTEL_SERVICE_NAME = _env("OTEL_SERVICE_NAME", "agent-hangar")
