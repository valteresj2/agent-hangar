"""Configuração do Agent Hangar — tudo vem de variáveis de ambiente (ver .env.example)."""
import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


APP_NAME = "Agent Hangar"
VERSION = "0.2.1"

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
INTERNAL_BASE_URL = _env("INTERNAL_BASE_URL", "http://central:8080").rstrip("/")

# Imagens. HANGAR_REGISTRY=ghcr.io/<owner> usa as imagens publicadas; o padrão usa os builds locais.
REGISTRY = _env("HANGAR_REGISTRY", "agent-hangar").rstrip("/")
IMAGE_TAG = _env("HANGAR_VERSION", "latest")
RUNTIME_IMAGE = _env("RUNTIME_IMAGE", f"{REGISTRY}/agent-runtime:{IMAGE_TAG}")


def harness_image(harness_id: str) -> str:
    """Imagem do container de job. `base` roda o modo mock (sem nenhum CLI de harness instalado)."""
    override = _env(f"HARNESS_IMAGE_{harness_id.upper().replace('-', '_')}")
    return override or f"{REGISTRY}/harness-{harness_id}:{IMAGE_TAG}"


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
JOB_WORKERS = int(_env("JOB_WORKERS", "8"))

TEMPLATES_DIR = _env("TEMPLATES_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                  "templates"))
