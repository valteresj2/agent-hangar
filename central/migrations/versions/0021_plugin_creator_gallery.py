"""Plugins (P3 e P4): testes em stage (instalação de teste com o rascunho e o relatório preso à versão), vitrine
interna (categoria, tags, destaque, histórico de versões e pedidos de instalação dos times).

Revision ID: 0021_plugin_creator_gallery
Revises: 0020_plugin_oauth_triggers
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_plugin_creator_gallery"
down_revision = "0020_plugin_oauth_triggers"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("plugins") as b:
        b.add_column(sa.Column("test_report", sa.JSON, nullable=True))
        b.add_column(sa.Column("category", sa.String(40), nullable=False, server_default="other"))
        b.add_column(sa.Column("tags", sa.JSON, nullable=True))
        b.add_column(sa.Column("featured", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("history", sa.JSON, nullable=True))
        b.add_column(sa.Column("requests", sa.JSON, nullable=True))
    with op.batch_alter_table("plugin_installs") as b:
        b.add_column(sa.Column("stage", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("plugin_installs") as b:
        b.drop_column("stage")
    with op.batch_alter_table("plugins") as b:
        for c in ("requests", "history", "featured", "tags", "category", "test_report"):
            b.drop_column(c)
