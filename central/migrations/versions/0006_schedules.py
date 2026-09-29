"""agendamentos de agentes (cron ou data única) e histórico de execuções; fuso padrão da empresa

Revision ID: 0006_schedules
Revises: 0005_local_login
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_schedules"
down_revision = "0005_local_login"
branch_labels = None
depends_on = None


def _ts(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"))
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("cron", sa.String(120), nullable=True),
        _ts("run_at"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("notify_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("created_user_id", sa.Integer, nullable=True),
        _ts("next_run_at"), _ts("last_run_at"),
        sa.Column("last_status", sa.String(20), nullable=False, server_default=""),
        _ts("created_at"))
    op.create_index("ix_schedules_next_run_at", "schedules", ["next_run_at"])
    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("schedule_id", sa.Integer, sa.ForeignKey("schedules.id"), nullable=False, index=True),
        sa.Column("agent_id", sa.Integer, nullable=False, index=True),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="schedule"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("version", sa.Integer, nullable=True),
        sa.Column("output", sa.Text, nullable=False, server_default=""),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("notify_status", sa.String(200), nullable=False, server_default=""),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        _ts("started_at"), _ts("finished_at"))


def downgrade():
    op.drop_table("schedule_runs")
    op.drop_index("ix_schedules_next_run_at", "schedules")
    op.drop_table("schedules")
    with op.batch_alter_table("organizations") as b:
        b.drop_column("timezone")
