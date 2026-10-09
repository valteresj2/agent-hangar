"""Decisões fora do portal (Slack, Teams, e-mail), resumo diário, alerta de expiração e prazos de tarefa.

Revision ID: 0017_decision_channels
Revises: 0016_employee_shadow_career
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_decision_channels"
down_revision = "0016_employee_shadow_career"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("notify", sa.JSON, nullable=True))
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("notify", sa.JSON, nullable=True))
    with op.batch_alter_table("human_requests") as b:
        b.add_column(sa.Column("reminded", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("chat_refs", sa.JSON, nullable=True))
    with op.batch_alter_table("employee_tasks") as b:
        b.add_column(sa.Column("due_state", sa.String(12), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("employee_tasks") as b:
        b.drop_column("due_state")
    with op.batch_alter_table("human_requests") as b:
        b.drop_column("chat_refs")
        b.drop_column("reminded")
    with op.batch_alter_table("users") as b:
        b.drop_column("notify")
    with op.batch_alter_table("organizations") as b:
        b.drop_column("notify")
