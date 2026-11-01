"""Data em que o provedor descontinua cada modelo (da tabela pública do LiteLLM ou informada pelo admin), para avisar
quem usa antes de o agente parar.

Revision ID: 0055_model_deprecation
Revises: 0054_app_events
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_model_deprecation"
down_revision = "0054_app_events"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("llm_models") as b:
        b.add_column(sa.Column("deprecates_on", sa.Date(), nullable=True))
        b.add_column(sa.Column("deprecation_source", sa.String(10), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("llm_models") as b:
        b.drop_column("deprecation_source")
        b.drop_column("deprecates_on")
