"""Digital employee: modo sombra (ações externas simuladas e revisadas pelo gestor) e plano de carreira (histórico de
mudanças de nível).

Revision ID: 0016_employee_shadow_career
Revises: 0015_employee_run_code
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_employee_shadow_career"
down_revision = "0015_employee_run_code"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employees") as b:
        b.add_column(sa.Column("shadow", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("career", sa.JSON, nullable=True))


def downgrade():
    with op.batch_alter_table("employees") as b:
        b.drop_column("career")
        b.drop_column("shadow")
