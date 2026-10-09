"""Plugins (P2a): credencial OAuth2 por instalação e gatilhos (eventos do sistema que viram tarefas de um Digital
employee), com o token do webhook guardado só como hash.

Revision ID: 0020_plugin_oauth_triggers
Revises: 0019_plugins
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_plugin_oauth_triggers"
down_revision = "0019_plugins"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("plugin_installs") as b:
        b.add_column(sa.Column("triggers", sa.JSON, nullable=True))
        b.add_column(sa.Column("hook_token_hash", sa.String(64), nullable=False, server_default=""))
        b.add_column(sa.Column("hook_token_hint", sa.String(12), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("plugin_installs") as b:
        b.drop_column("hook_token_hint")
        b.drop_column("hook_token_hash")
        b.drop_column("triggers")
