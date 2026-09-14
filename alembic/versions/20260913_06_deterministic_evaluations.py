"""Add explicit compensation periods and explainable evaluation history."""
from alembic import op
import sqlalchemy as sa

revision = "20260913_06"
down_revision = "20260913_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No backfill: previously unspecified compensation periods remain unknown.
    for table in ("jobs", "applicants"):
        op.add_column(table, sa.Column("salary_period", sa.String(16), nullable=True))
    for column in (
        sa.Column("rules_version", sa.String(64), nullable=True),
        sa.Column("input_fingerprint", sa.String(64), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("input_context", sa.JSON(), nullable=True),
    ):
        op.add_column("job_evaluations", column)
    op.create_index("uq_evaluation_inputs", "job_evaluations",
                    ["job_id", "applicant_id", "input_fingerprint"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_evaluation_inputs", table_name="job_evaluations")
    with op.batch_alter_table("job_evaluations") as batch:
        for column in ("input_context", "reasons", "input_fingerprint", "rules_version"):
            batch.drop_column(column)
    for table in ("applicants", "jobs"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("salary_period")
