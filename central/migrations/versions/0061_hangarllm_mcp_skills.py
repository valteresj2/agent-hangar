"""HangarLLM como hub, etapa 2: os servidores MCP e as skills do gateway (services/hangarllm.py).

- hub_keys.mcps: os servidores MCP do hub que a chave do agente libera;
- hub_links.share_skills / sync: publicar as skills da empresa no hub e o resumo da última sincronização;
- skills.source / hub_ref: a skill veio do hub (somente leitura aqui) e a versão lida ou publicada.

Revision ID: 0061_hangarllm_mcp_skills
Revises: 0060_hangarllm_hub
"""
import sqlalchemy as sa
from alembic import op

revision = "0061_hangarllm_mcp_skills"
down_revision = "0060_hangarllm_hub"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hub_keys") as b:
        b.add_column(sa.Column("mcps", sa.JSON(), nullable=True))
    with op.batch_alter_table("hub_links") as b:
        b.add_column(sa.Column("share_skills", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.add_column(sa.Column("sync", sa.JSON(), nullable=True))
    with op.batch_alter_table("skills") as b:
        b.add_column(sa.Column("source", sa.String(12), nullable=False, server_default=""))
        b.add_column(sa.Column("hub_ref", sa.String(40), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("skills") as b:
        b.drop_column("hub_ref")
        b.drop_column("source")
    with op.batch_alter_table("hub_links") as b:
        b.drop_column("sync")
        b.drop_column("share_skills")
    with op.batch_alter_table("hub_keys") as b:
        b.drop_column("mcps")
