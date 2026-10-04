"""Guia dos agentes: o que é, o que faz e como usar, por versão (fora da spec: documentação não exige novo teste).

Revision ID: 0012_agent_guides
Revises: 0011_composer
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_agent_guides"
down_revision = "0011_composer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_guides",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="author"),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("agent_id", "version"),
    )


def downgrade():
    op.drop_table("agent_guides")
