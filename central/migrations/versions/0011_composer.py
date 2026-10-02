"""Montagem de agentes a partir do catálogo: linhagem dos agentes montados e skills como peças (versão, exemplos,
teste próprio, time e autor).

Revision ID: 0011_composer
Revises: 0010_oauth_ha
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_composer"
down_revision = "0010_oauth_ha"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("skills", sa.Column("examples", sa.Text, nullable=False, server_default=""))
    op.add_column("skills", sa.Column("test", sa.JSON, nullable=True))
    op.add_column("skills", sa.Column("version", sa.Integer, nullable=False, server_default="1"))
    op.add_column("skills", sa.Column("team_id", sa.Integer, nullable=True))
    op.add_column("skills", sa.Column("created_by", sa.String(200), nullable=False, server_default=""))
    op.create_table(
        "agent_lineage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("plan_id", sa.String(40), nullable=False, server_default=""),
        sa.Column("mode", sa.String(20), nullable=False, server_default="scratch"),
        sa.Column("based_on", sa.JSON, nullable=True),
        sa.Column("specialists", sa.JSON, nullable=False),
        sa.Column("skills", sa.JSON, nullable=False),
        sa.Column("new_skills", sa.JSON, nullable=False),
        sa.Column("tests_copied", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reused_chars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("written_chars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("agent_lineage")
    for c in ("created_by", "team_id", "version", "test", "examples"):
        op.drop_column("skills", c)
