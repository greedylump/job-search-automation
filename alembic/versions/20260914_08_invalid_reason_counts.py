"""Add aggregate invalid-record reasons; historical breakdowns remain unknown."""
from alembic import op
import sqlalchemy as sa

revision = "20260914_08"
down_revision = "20260914_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_runs", sa.Column("invalid_reason_counts", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch:
        batch.drop_column("invalid_reason_counts")
