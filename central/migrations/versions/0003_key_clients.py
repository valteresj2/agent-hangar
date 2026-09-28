"""chaves de conexão por ferramenta: client (claude-code, librechat…) e mode (mcp | model)

Revision ID: 0003_key_clients
Revises: 0002_api_keys_costs
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_key_clients"
down_revision = "0002_api_keys_costs"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("api_keys") as b:
        b.add_column(sa.Column("client", sa.String(40), nullable=True))
        b.add_column(sa.Column("mode", sa.String(10), nullable=True))


def downgrade():
    with op.batch_alter_table("api_keys") as b:
        b.drop_column("mode")
        b.drop_column("client")
