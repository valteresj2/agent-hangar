"""catálogo Docker MCP: servidores ativados no gateway e prefixo de ferramentas por item do catálogo

Revision ID: 0007_mcp_gateway
Revises: 0006_schedules
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_mcp_gateway"
down_revision = "0006_schedules"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("mcp_servers") as b:
        b.add_column(sa.Column("tool_prefix", sa.String(100), nullable=False, server_default=""))
    op.create_table(
        "gateway_servers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("secrets", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_table("gateway_servers")
    with op.batch_alter_table("mcp_servers") as b:
        b.drop_column("tool_prefix")
