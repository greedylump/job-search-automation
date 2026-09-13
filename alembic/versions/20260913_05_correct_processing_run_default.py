"""Start new processing runs as running without changing historical statuses."""
from alembic import op
import sqlalchemy as sa

revision = "20260913_05"
down_revision = "20260912_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch:
        batch.alter_column("status", existing_type=sa.String(32),
                           existing_nullable=False, server_default="running")


def downgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch:
        batch.alter_column("status", existing_type=sa.String(32),
                           existing_nullable=False, server_default="completed")
