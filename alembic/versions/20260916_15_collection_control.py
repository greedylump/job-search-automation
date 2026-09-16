"""Persistent global collection control."""
from alembic import op
import sqlalchemy as sa

revision = '20260916_15'
down_revision = '20260915_14'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('collection_control',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.execute("INSERT INTO collection_control VALUES (1, NULL, CURRENT_TIMESTAMP)")


def downgrade():
    op.drop_table('collection_control')
