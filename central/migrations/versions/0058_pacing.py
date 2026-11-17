"""Ritmo das mensagens dos Digital employees: a configuração por funcionário e o registro das mensagens enviadas e
seguradas (services/pacing.py).

Revision ID: 0058_pacing
Revises: 0057_recordings
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_pacing"
down_revision = "0057_recordings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employees", sa.Column("pacing", sa.JSON(), nullable=True))
    op.create_table(
        "paced_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("user_id", sa.Integer(), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer(), nullable=False, index=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(10), nullable=False, server_default="sent", index=True),
        sa.Column("reason", sa.String(10), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("paced_messages")
    op.drop_column("employees", "pacing")
