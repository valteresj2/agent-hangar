"""Gravar uma tarefa: a gravação que a pessoa fez no app (os passos, a explicação, o rascunho do funcionário) e o aviso
de computador bloqueado (workstations.locked).

Revision ID: 0057_recordings
Revises: 0056_workstations
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_recordings"
down_revision = "0056_workstations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="drafted"),
        sa.Column("package", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.String(200), nullable=False, server_default=""),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("workstation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("workstations", sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("workstations", "locked")
    op.drop_table("recordings")
