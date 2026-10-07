"""Digital employee: delegar código a um agente com harness é o tipo de ação `run_code`, que pede aprovação no piso da
empresa (o admin pode mudar em Digital employees → Piso da empresa).

Revision ID: 0015_employee_run_code
Revises: 0014_employee_f2
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_employee_run_code"
down_revision = "0014_employee_f2"
branch_labels = None
depends_on = None


def upgrade():
    floor = sa.table("org_authority_floor", sa.column("action_type", sa.String), sa.column("min_mode", sa.String),
                     sa.column("separation", sa.Boolean), sa.column("updated_by", sa.String))
    exists = op.get_bind().execute(sa.text("SELECT 1 FROM org_authority_floor WHERE action_type = 'run_code'")).first()
    if not exists:
        op.bulk_insert(floor, [{"action_type": "run_code", "min_mode": "approve", "separation": False, "updated_by": "default"}])
    # ferramentas "agent:<slug>" de agentes com harness já classificadas como delegate passam a run_code na próxima
    # chamada (employee_gate.classify); nada a migrar aqui


def downgrade():
    op.execute("DELETE FROM org_authority_floor WHERE action_type = 'run_code'")
