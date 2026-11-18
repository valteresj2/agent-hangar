"""Curadoria noturna das lições dos Digital employees: as propostas da última revisão (services/curation.py).

Revision ID: 0059_curation
Revises: 0058_pacing
"""
import sqlalchemy as sa
from alembic import op

revision = "0059_curation"
down_revision = "0058_pacing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employees", sa.Column("curation", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("employees", "curation")
