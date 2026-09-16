"""Add sanitized request descriptors and response metrics."""
from alembic import op
import sqlalchemy as sa

revision = "20260915_13"
down_revision = "20260915_12"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("request_method", sa.String(8)),
        sa.Column("request_purpose", sa.String(16)),
        sa.Column("request_metadata", sa.JSON()),
        sa.Column("response_bytes", sa.Integer()),
        sa.Column("records_returned", sa.Integer()),
    ):
        op.add_column("request_attempts", column)


def downgrade():
    for name in ("records_returned", "response_bytes", "request_metadata", "request_purpose", "request_method"):
        op.drop_column("request_attempts", name)
