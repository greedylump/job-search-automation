"""Track source policies, request reservations, and skipped/replayed runs."""
from alembic import op
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa

revision = "20260914_09"
down_revision = "20260914_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sources = op.create_table(
        "job_sources",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("endpoint", sa.String(512), nullable=False),
        sa.Column("collection_strategy", sa.String(32), nullable=False),
        sa.Column("response_retention", sa.String(32), nullable=False),
        sa.Column("min_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("request_attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("next_allowed_at", sa.DateTime(), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
    )
    op.add_column("processing_runs", sa.Column("collection_mode", sa.String(16), nullable=True))
    op.add_column("processing_runs", sa.Column("skip_reason", sa.Text(), nullable=True))
    op.add_column("processing_runs", sa.Column("next_eligible_at", sa.DateTime(), nullable=True))
    # Older runs do not distinguish cached replays from HTTP. Preserve that
    # uncertainty, but conservatively avoid fetching within six hours of a run.
    latest = op.get_bind().execute(sa.text(
        "SELECT MAX(started_at) FROM processing_runs WHERE source = 'remotive'"
    )).scalar()
    if latest is not None:
        observed = datetime.fromisoformat(str(latest))
        if observed.tzinfo is not None:
            observed = observed.astimezone(timezone.utc).replace(tzinfo=None)
        op.bulk_insert(sources, [{
            "name": "remotive", "endpoint": "https://remotive.com/api/remote-jobs",
            "collection_strategy": "full_feed", "response_retention": "none",
            "min_interval_seconds": 21600, "request_attempts": 0,
            "next_allowed_at": observed + timedelta(hours=6),
        }])


def downgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch:
        for name in ("next_eligible_at", "skip_reason", "collection_mode"):
            batch.drop_column(name)
    op.drop_table("job_sources")
