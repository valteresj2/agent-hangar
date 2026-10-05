"""Digital employee (F1): cargo, alçada, piso da empresa, catálogo de ações, tarefas com checkpoints, humano no
circuito e relatórios.

Revision ID: 0013_digital_employees
Revises: 0012_agent_guides
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_digital_employees"
down_revision = "0012_agent_guides"
branch_labels = None
depends_on = None

FLOOR = [("financial", "approve_2", True), ("delete", "approve", True), ("prod_change", "approve", True),
         ("send_external", "approve", False), ("speak_for_company", "approve", False), ("publish", "approve", False)]


def upgrade():
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("team_id", sa.Integer, nullable=True, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("mission", sa.Text, nullable=False, server_default=""),
        sa.Column("responsibilities", sa.JSON, nullable=False),
        sa.Column("kpis", sa.JSON, nullable=False),
        sa.Column("systems", sa.JSON, nullable=False),
        sa.Column("channels", sa.JSON, nullable=False),
        sa.Column("owner_user_id", sa.Integer, nullable=True),
        sa.Column("manager_user_id", sa.Integer, nullable=False),
        sa.Column("backup_user_ids", sa.JSON, nullable=False),
        sa.Column("autonomy_level", sa.String(12), nullable=False, server_default="intern"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("working_hours", sa.String(60), nullable=False, server_default=""),
        sa.Column("task_budget_usd", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("task_time_limit_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("report_webhook", sa.String(500), nullable=False, server_default=""),
        sa.Column("report_hour", sa.Integer, nullable=False, server_default="18"),
        sa.Column("last_report_on", sa.String(10), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("created_at", ts), sa.Column("hired_at", ts), sa.Column("offboarded_at", ts),
    )
    op.create_table(
        "authority_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("conditions", sa.JSON, nullable=False),
        sa.Column("approver", sa.String(254), nullable=False, server_default="manager"),
        sa.Column("expires_in_min", sa.Integer, nullable=False, server_default="240"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
    )
    op.create_table(
        "action_catalog",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tool_ref", sa.String(300), nullable=False, unique=True, index=True),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("risk", sa.Integer, nullable=False, server_default="3"),
        sa.Column("reversible", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("classified_by", sa.String(254), nullable=False, server_default="auto"),
        sa.Column("updated_at", ts),
    )
    floor = op.create_table(
        "org_authority_floor",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("action_type", sa.String(30), nullable=False, unique=True),
        sa.Column("min_mode", sa.String(12), nullable=False),
        sa.Column("separation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.String(254), nullable=False, server_default=""),
    )
    op.bulk_insert(floor, [{"action_type": a, "min_mode": m, "separation": s, "updated_by": "default"} for a, m, s in FLOOR])
    op.create_table(
        "employee_tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="portal"),
        sa.Column("requester", sa.String(254), nullable=False, server_default=""),
        sa.Column("requester_user_id", sa.Integer, nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("expected", sa.Text, nullable=False, server_default=""),
        sa.Column("probation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("priority", sa.Integer, nullable=False, server_default="2"),
        sa.Column("due_at", ts),
        sa.Column("status", sa.String(20), nullable=False, server_default="new", index=True),
        sa.Column("result", sa.Text, nullable=False, server_default=""),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("worker", sa.String(80), nullable=False, server_default=""),
        sa.Column("started_at", ts), sa.Column("finished_at", ts), sa.Column("created_at", ts), sa.Column("updated_at", ts),
    )
    op.create_table(
        "employee_task_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("employee_tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("at", ts),
    )
    op.create_table(
        "employee_task_checkpoints",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("employee_tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("messages", sa.JSON, nullable=False),
        sa.Column("at", ts),
    )
    op.create_table(
        "human_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("task_id", sa.Integer, nullable=True, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False, server_default=""),
        sa.Column("mode", sa.String(12), nullable=False, server_default="approve"),
        sa.Column("tool_ref", sa.String(300), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("action_payload", sa.JSON, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text, nullable=False, server_default=""),
        sa.Column("risk", sa.Integer, nullable=False, server_default="3"),
        sa.Column("reversible", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("question", sa.Text, nullable=False, server_default=""),
        sa.Column("assigned_user_id", sa.Integer, nullable=True, index=True),
        sa.Column("fallback_user_id", sa.Integer, nullable=True),
        sa.Column("escalated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("expires_at", ts),
        sa.Column("status", sa.String(12), nullable=False, server_default="open", index=True),
        sa.Column("approvals", sa.JSON, nullable=False),
        sa.Column("decision", sa.String(20), nullable=False, server_default=""),
        sa.Column("edited_payload", sa.JSON, nullable=True),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(254), nullable=False, server_default=""),
        sa.Column("decided_at", ts),
        sa.Column("grant_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("grant_used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", ts),
    )
    op.create_table(
        "employee_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("period", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("sent_to", sa.String(500), nullable=False, server_default=""),
        sa.Column("delivered", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("at", ts),
    )


def downgrade():
    for t in ("employee_reports", "human_requests", "employee_task_checkpoints", "employee_task_events",
              "employee_tasks", "org_authority_floor", "action_catalog", "authority_rules", "employees"):
        op.drop_table(t)
