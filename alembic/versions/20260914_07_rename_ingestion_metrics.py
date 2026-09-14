"""Rename input metrics without changing historical counts."""
from alembic import op
import sqlalchemy as sa

revision = "20260914_07"
down_revision = "20260913_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch:
        batch.alter_column("jobs_seen", new_column_name="records_seen",
                           existing_type=sa.Integer(), existing_nullable=False)
        batch.alter_column("jobs_filtered", new_column_name="records_invalid",
                           existing_type=sa.Integer(), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch:
        batch.alter_column("records_seen", new_column_name="jobs_seen",
                           existing_type=sa.Integer(), existing_nullable=False)
        batch.alter_column("records_invalid", new_column_name="jobs_filtered",
                           existing_type=sa.Integer(), existing_nullable=False)
