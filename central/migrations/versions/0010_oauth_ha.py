"""OAuth do MCP (apps registrados e autorizações) e estado compartilhado para várias réplicas da central.

Revision ID: 0010_oauth_ha
Revises: 0009_code_policy
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_oauth_ha"
down_revision = "0009_code_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ephemeral",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("redirect_uris", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.String(64), sa.ForeignKey("oauth_clients.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("access_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("previous_refresh_hash", sa.String(64), nullable=False, server_default="", index=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("jobs", sa.Column("worker", sa.String(100), nullable=False, server_default=""))


def downgrade():
    op.drop_column("jobs", "worker")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")
    op.drop_table("ephemeral")
