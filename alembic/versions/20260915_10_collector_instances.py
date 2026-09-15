"""Add mutable adapter configuration to source instances."""
from alembic import op
import sqlalchemy as sa

revision = "20260915_10"
down_revision = "20260914_09"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("job_sources") as batch:
        batch.add_column(sa.Column("adapter_type", sa.String(32), nullable=False, server_default="remotive"))
        batch.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("job_sources") as batch:
        for name in ("adapter_type", "enabled", "settings"):
            batch.alter_column(name, server_default=None)


def downgrade():
    with op.batch_alter_table("job_sources") as batch:
        for name in ("settings", "enabled", "adapter_type"):
            batch.drop_column(name)
