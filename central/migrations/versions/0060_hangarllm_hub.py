"""HangarLLM como hub: a ligação da empresa e as chaves virtuais que a central cria para cada agente
(services/hangarllm.py).

Revision ID: 0060_hangarllm_hub
Revises: 0059_curation
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_hangarllm_hub"
down_revision = "0059_curation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hub_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("ui_url", sa.String(300), nullable=False, server_default=""),
        sa.Column("admin_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("budget_usd", sa.Float(), nullable=False, server_default="50"),
        sa.Column("budget_period", sa.String(10), nullable=False, server_default="30d"),
        sa.Column("status", sa.String(12), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", name="uq_hublink_org"),
    )
    op.create_table(
        "hub_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("agent_id", sa.Integer(), nullable=True, index=True),
        sa.Column("env", sa.String(10), nullable=False, server_default=""),
        sa.Column("alias", sa.String(200), nullable=False, index=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("token", sa.String(100), nullable=False, server_default=""),
        sa.Column("models", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spend_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spend_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("hub_keys")
    op.drop_table("hub_links")
