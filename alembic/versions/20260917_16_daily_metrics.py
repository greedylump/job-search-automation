"""Preserve aggregate metrics when detailed history expires."""
from alembic import op
import sqlalchemy as sa

revision = '20260917_16'
down_revision = '20260916_15'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('daily_metrics',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('day', sa.String(10), nullable=False),
        sa.Column('source', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('budget_name', sa.String(64)),
        sa.Column('dimensions', sa.JSON(), nullable=False),
        sa.Column('rows', sa.Integer(), nullable=False),
        sa.Column('totals', sa.JSON(), nullable=False),
        sa.Column('last_event_at', sa.DateTime(), nullable=False))
    op.create_index('ix_daily_metrics_day', 'daily_metrics', ['day'])
    op.create_index('ix_daily_metrics_budget_name', 'daily_metrics', ['budget_name'])


def downgrade():
    # Deleted detail cannot be reconstructed; never silently discard its rollups.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM daily_metrics')).scalar():
        raise RuntimeError('Cannot downgrade retained metrics; restore a pre-retention backup instead')
    op.drop_table('daily_metrics')
