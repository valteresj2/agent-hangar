"""Computadores compartilhados: a máquina de uma pessoa emprestada aos Digital employees (workstations), os
empréstimos (workstation_leases) e a fila de passos de tela (workstation_steps).

Revision ID: 0056_workstations
Revises: 0055_model_deprecation
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_workstations"
down_revision = "0055_model_deprecation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workstations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("os", sa.String(40), nullable=False, server_default=""),
        sa.Column("apps", sa.JSON(), nullable=False),
        sa.Column("allow_managed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_team_ids", sa.JSON(), nullable=False),
        sa.Column("auth_mode", sa.String(16), nullable=False, server_default="ask"),
        sa.Column("token_hash", sa.String(64), nullable=False, server_default="", index=True),
        sa.Column("token_hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("status", sa.String(10), nullable=False, server_default="on"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workstation_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("workstation_id", sa.Integer(), sa.ForeignKey("workstations.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("employee_id", sa.Integer(), nullable=False, index=True),
        sa.Column("task_id", sa.Integer(), nullable=False, index=True),
        sa.Column("app", sa.String(120), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="requested", index=True),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("ended_reason", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_step_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "workstation_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("workstation_leases.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("workstation_id", sa.Integer(), nullable=False, index=True),
        sa.Column("command", sa.String(20), nullable=False),
        sa.Column("args_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued", index=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("workstation_steps")
    op.drop_table("workstation_leases")
    op.drop_table("workstations")
