"""chaves de API com escopo; custo e tokens de jobs e de uso; preço por conexão

Revision ID: 0002_api_keys_costs
Revises: 0001_baseline
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_api_keys_costs"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade():
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("agents", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("last_used_at", TZ, nullable=True),
        sa.Column("revoked_at", TZ, nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    with op.batch_alter_table("llm_connections") as b:
        b.add_column(sa.Column("price_in_per_mtok", sa.Float(), nullable=True))
        b.add_column(sa.Column("price_out_per_mtok", sa.Float(), nullable=True))
    with op.batch_alter_table("usage_events") as b:
        b.add_column(sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"))
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("jobs") as b:
        b.drop_column("cost_usd")
        b.drop_column("tokens_out")
        b.drop_column("tokens_in")
    with op.batch_alter_table("usage_events") as b:
        b.drop_column("cost_usd")
    with op.batch_alter_table("llm_connections") as b:
        b.drop_column("price_out_per_mtok")
        b.drop_column("price_in_per_mtok")
    op.drop_index("ix_api_keys_key_hash", "api_keys")
    op.drop_table("api_keys")
