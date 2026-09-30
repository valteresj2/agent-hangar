"""Governança de código: política da empresa (qualquer conexão x só as aprovadas) e conexões de LLM aprovadas para
receber código (modo agente de código: VS Code, Cline, Continue e as avaliações de código em stage).

Revision ID: 0009_code_policy
Revises: 0008_remote_mcp
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_code_policy"
down_revision = "0008_remote_mcp"
branch_labels = None
depends_on = None


def upgrade():
    # "any" mantém o comportamento das instalações existentes; a empresa liga "approved" quando quiser travar
    op.add_column("organizations", sa.Column("code_policy", sa.String(10), nullable=False, server_default="any"))
    op.add_column("llm_connections", sa.Column("allow_code", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("llm_connections", "allow_code")
    op.drop_column("organizations", "code_policy")
