"""Separate collector refresh schedules from shared request budgets."""
from alembic import op
import sqlalchemy as sa

revision = "20260915_12"
down_revision = "20260915_11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("request_budgets",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("min_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_allowed_at", sa.DateTime()),
        sa.Column("last_attempt_at", sa.DateTime()),
        sa.CheckConstraint("min_interval_seconds >= 0", name="ck_budget_interval"))
    op.create_table("request_budget_windows",
        sa.Column("budget_name", sa.String(64), sa.ForeignKey("request_budgets.name"), primary_key=True),
        sa.Column("window_seconds", sa.Integer(), primary_key=True),
        sa.Column("max_requests", sa.Integer(), nullable=False),
        sa.CheckConstraint("window_seconds > 0", name="ck_window_seconds"),
        sa.CheckConstraint("max_requests > 0", name="ck_window_requests"))
    # ADD COLUMN avoids rebuilding tables referenced by historical ledger rows.
    op.execute("ALTER TABLE job_sources ADD COLUMN budget_name VARCHAR(64) REFERENCES request_budgets(name)")
    op.add_column("job_sources", sa.Column("refresh_interval_seconds", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job_sources", sa.Column("next_due_at", sa.DateTime()))
    op.add_column("job_sources", sa.Column("last_complete_refresh_at", sa.DateTime()))
    op.execute("ALTER TABLE request_attempts ADD COLUMN budget_name VARCHAR(64) REFERENCES request_budgets(name)")
    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO request_budgets (name,min_interval_seconds,next_allowed_at,last_attempt_at)
        SELECT adapter_type, MAX(min_interval_seconds), MAX(next_allowed_at), MAX(last_attempt_at)
        FROM job_sources WHERE adapter_type != 'json_fixture' GROUP BY adapter_type
    """))
    connection.execute(sa.text("""
        UPDATE job_sources SET budget_name=adapter_type,
            refresh_interval_seconds=min_interval_seconds
        WHERE adapter_type != 'json_fixture'
    """))
    connection.execute(sa.text("""
        UPDATE request_attempts SET budget_name=(SELECT budget_name FROM job_sources
            WHERE job_sources.name=request_attempts.source)
    """))
    op.create_index("ix_request_attempts_budget_name", "request_attempts", ["budget_name"])


def downgrade():
    op.drop_index("ix_request_attempts_budget_name", table_name="request_attempts")
    op.drop_column("request_attempts", "budget_name")
    for column in ("last_complete_refresh_at", "next_due_at", "refresh_interval_seconds", "budget_name"):
        op.drop_column("job_sources", column)
    op.drop_table("request_budget_windows")
    op.drop_table("request_budgets")
