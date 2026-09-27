"""Modelo de dados. Mudança de schema = nova migração em central/migrations/versions (Alembic)."""
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    final_output: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="single")  # single | multi
    owner: Mapped[str] = mapped_column(String(200), default="")
    # draft | tested | test_failed | stage | production
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    versions = relationship("AgentVersion", cascade="all, delete-orphan", order_by="AgentVersion.version.desc()")
    tests = relationship("TestRun", cascade="all, delete-orphan", order_by="TestRun.id.desc()")
    deployments = relationship("Deployment", cascade="all, delete-orphan", order_by="Deployment.id.desc()")
    jobs = relationship("Job", cascade="all, delete-orphan", order_by="Job.id.desc()")


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestRun(Base):
    __test__ = False
    __tablename__ = "test_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    env: Mapped[str] = mapped_column(String(20), default="stage")
    status: Mapped[str] = mapped_column(String(20))  # passed | failed
    summary: Mapped[str] = mapped_column(String(300), default="")
    results: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    env: Mapped[str] = mapped_column(String(20))  # stage | prod
    container_name: Mapped[str] = mapped_column(String(200), default="")
    container_id: Mapped[str] = mapped_column(String(80), default="")
    # running | failed | stopped | replaced | missing | exited
    status: Mapped[str] = mapped_column(String(20), default="starting")
    url: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    env: Mapped[str] = mapped_column(String(20), default="prod")
    channel: Mapped[str] = mapped_column(String(50), default="api")
    protocol: Mapped[str] = mapped_column(String(20), default="openai")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")


class McpServer(Base):
    __tablename__ = "mcp_servers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")


class LlmConnection(Base):
    """LLM externo (gateway LiteLLM corporativo, OpenRouter, provedor direto…). A plataforma nunca hospeda
    modelo: guarda url + model_name + chave (criptografada, ver crypto.py) e injeta no agente no deploy."""
    __tablename__ = "llm_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    base_url: Mapped[str] = mapped_column(String(300))
    model_name: Mapped[str] = mapped_column(String(150))
    api_key: Mapped[str] = mapped_column(Text, default="")  # "enc:v1:…" — nunca exposta via API
    description: Mapped[str] = mapped_column(Text, default="")
    # openai (chat, codex, hermes) | anthropic (claude-code) | deepseek (deepseek-harness)
    protocol: Mapped[str] = mapped_column(String(20), default="openai")
    # Preço por 1M tokens (US$), para calcular custo por chamada. Opcional.
    price_in_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_out_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    """Uma execução de agente-com-harness: container efêmero, 1 por job, sem socket do Docker. O container
    roda a tarefa e chama de volta /internal/jobs/<id>/callback; nenhum container de harness fica ocioso."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    env: Mapped[str] = mapped_column(String(20), default="stage")
    harness_id: Mapped[str] = mapped_column(String(50), default="claude-code")
    connection: Mapped[str] = mapped_column(String(100), default="")
    task: Mapped[str] = mapped_column(Text)
    # queued | running | passed | failed | timeout | error | cancelled
    status: Mapped[str] = mapped_column(String(20), default="running")
    result: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[str] = mapped_column(Text, default="")
    logs: Mapped[str] = mapped_column(Text, default="")
    token: Mapped[str] = mapped_column(String(80), default="")  # segredo do callback — nunca exposto via API
    container_name: Mapped[str] = mapped_column(String(200), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    """Chave de API com escopo. Só o hash é guardado; o valor aparece uma única vez, na criação.
    scopes: ["admin"] (tudo) ou ["invoke"] (só chamar agentes pelo gateway /gw); agents limita o invoke
    a alguns slugs (lista vazia = todos)."""
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(20))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    agents: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
