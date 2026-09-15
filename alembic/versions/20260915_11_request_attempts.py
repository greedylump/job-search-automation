"""Preserve individual HTTP reservations and outcomes linked to processing runs."""
from alembic import op
import sqlalchemy as sa

revision = "20260915_11"
down_revision = "20260915_10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("processing_run_id", sa.Integer(), sa.ForeignKey("processing_runs.id"), nullable=False),
        sa.Column("source", sa.String(64), sa.ForeignKey("job_sources.name"), nullable=False),
        sa.Column("endpoint", sa.String(512), nullable=False),
        sa.Column("reserved_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("retry_at", sa.DateTime()),
        sa.Column("next_allowed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_request_attempts_processing_run_id", "request_attempts", ["processing_run_id"])


def downgrade():
    op.drop_table("request_attempts")
