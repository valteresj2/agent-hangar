"""MCPs remotos com OAuth (tokens criptografados, renovação automática, proxy interno para os agentes)

Revision ID: 0008_remote_mcp
Revises: 0007_mcp_gateway
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_remote_mcp"
down_revision = "0007_mcp_gateway"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "remote_mcps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("browser_base", sa.String(300), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("oauth", sa.JSON, nullable=True),
        sa.Column("client_secret", sa.Text, nullable=False, server_default=""),
        sa.Column("access_token", sa.Text, nullable=False, server_default=""),
        sa.Column("refresh_token", sa.Text, nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("connected_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_table("remote_mcps")
