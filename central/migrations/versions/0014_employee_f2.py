"""Digital employee (F2): rotinas (trabalho recorrente), webhook de entrada com deduplicação, metas medidas, relatório
semanal, lições aprendidas com as decisões e espera crescente entre tentativas.

Revision ID: 0014_employee_f2
Revises: 0013_digital_employees
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_employee_f2"
down_revision = "0013_digital_employees"
branch_labels = None
depends_on = None


def upgrade():
    ts = sa.DateTime(timezone=True)
    with op.batch_alter_table("employees") as b:
        b.add_column(sa.Column("webhook_token_hash", sa.String(64), nullable=False, server_default=""))
        b.add_column(sa.Column("webhook_token_hint", sa.String(12), nullable=False, server_default=""))
        b.add_column(sa.Column("lessons", sa.JSON, nullable=True))
        b.add_column(sa.Column("dismissed", sa.JSON, nullable=True))
        b.add_column(sa.Column("report_weekday", sa.Integer, nullable=False, server_default="0"))
        b.add_column(sa.Column("last_weekly_on", sa.String(10), nullable=False, server_default=""))
    with op.batch_alter_table("employee_tasks") as b:
        b.add_column(sa.Column("not_before", ts, nullable=True))
        b.add_column(sa.Column("dedupe_key", sa.String(200), nullable=False, server_default=""))
        b.add_column(sa.Column("routine_id", sa.Integer, nullable=True))
        b.create_index("ix_employee_tasks_dedupe", ["employee_id", "dedupe_key"])
    op.create_table(
        "employee_routines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("cron", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="UTC"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="2"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", ts, nullable=True, index=True),
        sa.Column("last_run_at", ts, nullable=True),
        sa.Column("last_task_id", sa.Integer, nullable=True),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("created_at", ts, nullable=False),
    )


def downgrade():
    op.drop_table("employee_routines")
    with op.batch_alter_table("employee_tasks") as b:
        b.drop_index("ix_employee_tasks_dedupe")
        b.drop_column("routine_id")
        b.drop_column("dedupe_key")
        b.drop_column("not_before")
    with op.batch_alter_table("employees") as b:
        for c in ("last_weekly_on", "report_weekday", "dismissed", "lessons", "webhook_token_hint", "webhook_token_hash"):
            b.drop_column(c)
