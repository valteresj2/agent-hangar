"""contas locais: usuário e senha (hash scrypt), opcionais

Revision ID: 0005_local_login
Revises: 0004_org_access
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_local_login"
down_revision = "0004_org_access"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("username", sa.String(80), nullable=True))
        b.add_column(sa.Column("password_hash", sa.String(300), nullable=True))
        b.create_index("ix_users_username", ["username"], unique=True)


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_username")
        b.drop_column("password_hash")
        b.drop_column("username")
