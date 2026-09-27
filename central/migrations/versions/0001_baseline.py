"""baseline: schema da versão pré-Alembic (create_all + coluna protocol)

Bancos antigos são carimbados nesta revisão (ver app/db.py); bancos novos a criam do zero.

Revision ID: 0001_baseline
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade():
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("final_output", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("owner", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
    )
    op.create_index("ix_agents_slug", "agents", ["slug"], unique=True)
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("env", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("env", sa.String(20), nullable=False),
        sa.Column("container_name", sa.String(200), nullable=False),
        sa.Column("container_id", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("stopped_at", TZ, nullable=True),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("env", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_usage_events_agent_id", "usage_events", ["agent_id"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_table(
        "llm_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("base_url", sa.String(300), nullable=False),
        sa.Column("model_name", sa.String(150), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False, server_default="openai"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("env", sa.String(20), nullable=False),
        sa.Column("harness_id", sa.String(50), nullable=False),
        sa.Column("connection", sa.String(100), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("logs", sa.Text(), nullable=False),
        sa.Column("token", sa.String(80), nullable=False),
        sa.Column("container_name", sa.String(200), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("finished_at", TZ, nullable=True),
    )
    op.create_index("ix_jobs_agent_id", "jobs", ["agent_id"])


def downgrade():
    for t in ("jobs", "llm_connections", "mcp_servers", "skills", "audit_log", "usage_events", "deployments",
              "test_runs", "agent_versions", "agents"):
        op.drop_table(t)
