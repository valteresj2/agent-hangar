"""Digital employee: repasse de tarefa entre funcionários (com rastreio), plano visível (e aprovado) em tarefas longas,
memória do próprio trabalho e caixa de e-mail como canal de entrada.

Revision ID: 0018_employee_teamwork
Revises: 0017_decision_channels
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_employee_teamwork"
down_revision = "0017_decision_channels"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employees") as b:
        b.add_column(sa.Column("colleagues", sa.JSON, nullable=True))
        b.add_column(sa.Column("plan_policy", sa.String(10), nullable=False, server_default="auto"))
        b.add_column(sa.Column("recall", sa.Boolean, nullable=False, server_default=sa.true()))
        b.add_column(sa.Column("inbox", sa.JSON, nullable=True))
    with op.batch_alter_table("employee_tasks") as b:
        b.add_column(sa.Column("parent_task_id", sa.Integer, nullable=True))
        b.add_column(sa.Column("waiting_on", sa.Integer, nullable=True))
        b.add_column(sa.Column("plan", sa.JSON, nullable=True))
        b.add_column(sa.Column("plan_state", sa.String(12), nullable=False, server_default=""))
        b.add_column(sa.Column("plan_approval", sa.Boolean, nullable=False, server_default=sa.false()))
        b.create_index("ix_employee_tasks_parent_task_id", ["parent_task_id"])


def downgrade():
    with op.batch_alter_table("employee_tasks") as b:
        b.drop_index("ix_employee_tasks_parent_task_id")
        for c in ("plan_approval", "plan_state", "plan", "waiting_on", "parent_task_id"):
            b.drop_column(c)
    with op.batch_alter_table("employees") as b:
        for c in ("inbox", "recall", "plan_policy", "colleagues"):
            b.drop_column(c)
