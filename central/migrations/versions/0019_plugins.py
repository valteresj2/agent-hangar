"""Plugins (P1): pacotes declarativos que conectam um sistema à plataforma (ferramentas HTTP, credencial, tipos de
ação para a alçada, configurações e skills), com revisão de quatro olhos e instalação por time.

Revision ID: 0019_plugins
Revises: 0018_employee_teamwork
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_plugins"
down_revision = "0018_employee_teamwork"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plugins",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("version", sa.String(30), nullable=False, server_default=""),
        sa.Column("manifest", sa.JSON, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("source", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("team_id", sa.Integer, nullable=True),
        sa.Column("approved_manifest", sa.JSON, nullable=True),
        sa.Column("approved_version", sa.String(30), nullable=False, server_default=""),
        sa.Column("approved_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text, nullable=False, server_default=""),
        sa.Column("submitted_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "plugin_installs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plugin_id", sa.Integer, sa.ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("team_id", sa.Integer, nullable=True, index=True),
        sa.Column("settings", sa.JSON, nullable=True),
        sa.Column("secret", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("stats", sa.JSON, nullable=True),
        sa.Column("last_test", sa.JSON, nullable=True),
        sa.Column("installed_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("plugin_installs")
    op.drop_table("plugins")
