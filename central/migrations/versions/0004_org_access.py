"""empresa, times, usuários, sessões, pedidos de acesso/promoção, SSO (OAuth2) e SCIM

Os agentes que já existem vão para o time "Plataforma", com visibilidade "org".

Revision ID: 0004_org_access
Revises: 0003_key_clients
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_org_access"
down_revision = "0003_key_clients"
branch_labels = None
depends_on = None


def _ts(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("default_visibility", sa.String(10), nullable=False, server_default="org"),
        _ts("created_at"))
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, nullable=False, server_default="1", index=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("require_approval", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("budget_usd_month", sa.Float, nullable=True),
        sa.Column("budget_enforce", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("budget_alerted", sa.String(7), nullable=False, server_default=""),
        _ts("created_at"))
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, nullable=False, server_default="1", index=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("org_role", sa.String(10), nullable=False, server_default="member"),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("subject", sa.String(200), nullable=True),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        _ts("created_at"), _ts("last_login_at"))
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("role", sa.String(12), nullable=False, server_default="consumer"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        _ts("created_at"),
        sa.UniqueConstraint("team_id", "user_id"))
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("admin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        _ts("created_at"), _ts("expires_at", nullable=False), _ts("revoked_at"))
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(254), nullable=False, server_default=""),
        _ts("decided_at"), _ts("created_at"))
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agents.id"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("requested_by", sa.String(254), nullable=False),
        sa.Column("requested_user_id", sa.Integer, nullable=True),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(254), nullable=False, server_default=""),
        _ts("decided_at"), _ts("created_at"))
    op.create_table(
        "sso_providers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("client_id", sa.String(300), nullable=False, server_default=""),
        sa.Column("client_secret", sa.Text, nullable=False, server_default=""),
        sa.Column("settings", sa.JSON, nullable=True),
        _ts("updated_at"))
    op.create_table(
        "group_mappings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("external_group", sa.String(300), nullable=False),
        sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("role", sa.String(12), nullable=False, server_default="consumer"))
    op.create_table(
        "scim_groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("members", sa.JSON, nullable=True),
        _ts("created_at"))

    with op.batch_alter_table("agents") as b:
        b.add_column(sa.Column("org_id", sa.Integer, nullable=False, server_default="1"))
        b.add_column(sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id", name="fk_agents_team"),
                               nullable=True))
        b.add_column(sa.Column("visibility", sa.String(10), nullable=False, server_default="org"))
        b.add_column(sa.Column("expose_spec", sa.Boolean, nullable=False, server_default=sa.false()))
        b.create_index("ix_agents_team_id", ["team_id"])
        b.create_index("ix_agents_org_id", ["org_id"])
    with op.batch_alter_table("api_keys") as b:
        b.add_column(sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", name="fk_api_keys_user"),
                               nullable=True))
        b.create_index("ix_api_keys_user_id", ["user_id"])
    with op.batch_alter_table("usage_events") as b:
        b.add_column(sa.Column("user_id", sa.Integer, nullable=True))

    now = sa.func.now()
    op.execute(sa.table("organizations", sa.column("id"), sa.column("name"), sa.column("created_at"))
               .insert().values(id=1, name="Minha empresa", created_at=now))
    op.execute(sa.table("teams", sa.column("id"), sa.column("org_id"), sa.column("slug"), sa.column("name"),
                        sa.column("description"), sa.column("created_at"))
               .insert().values(id=1, org_id=1, slug="plataforma", name="Plataforma",
                                description="Time padrão: agentes criados antes dos times e pelo token de admin.",
                                created_at=now))
    op.execute("UPDATE agents SET team_id = 1")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":  # os ids 1 foram inseridos à mão: acerta as sequências
        op.execute("SELECT setval(pg_get_serial_sequence('organizations', 'id'), 1)")
        op.execute("SELECT setval(pg_get_serial_sequence('teams', 'id'), 1)")


def downgrade():
    with op.batch_alter_table("usage_events") as b:
        b.drop_column("user_id")
    with op.batch_alter_table("api_keys") as b:
        b.drop_index("ix_api_keys_user_id")
        b.drop_constraint("fk_api_keys_user", type_="foreignkey")
        b.drop_column("user_id")
    with op.batch_alter_table("agents") as b:
        b.drop_index("ix_agents_org_id")
        b.drop_index("ix_agents_team_id")
        b.drop_constraint("fk_agents_team", type_="foreignkey")
        for c in ("expose_spec", "visibility", "team_id", "org_id"):
            b.drop_column(c)
    for t in ("scim_groups", "group_mappings", "sso_providers", "promotion_requests", "access_requests",
              "user_sessions", "team_members", "users", "teams", "organizations"):
        op.drop_table(t)
