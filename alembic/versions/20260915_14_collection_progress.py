"""Persist continuation progress and fenced collector leases."""
from alembic import op
import sqlalchemy as sa

revision = "20260915_14"
down_revision = "20260915_13"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("continuation", sa.JSON()),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime()),
    ):
        op.add_column("job_sources", column)
    op.add_column("processing_runs", sa.Column("pages_collected", sa.Integer()))


def downgrade():
    op.drop_column("processing_runs", "pages_collected")
    for name in ("lease_expires_at", "lease_token", "continuation"):
        op.drop_column("job_sources", name)
