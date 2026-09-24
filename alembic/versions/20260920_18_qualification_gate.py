"""Explicit applicant experience evidence and prospective-queue disposition."""
from alembic import op
import sqlalchemy as sa

revision = '20260920_18'
down_revision = '20260918_17'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('applicants', sa.Column('experience_evidence', sa.JSON(), nullable=True))
    op.add_column('job_evaluations', sa.Column('queue_state', sa.String(32), nullable=True))


def downgrade():
    # Snapshots preserve evaluation evidence, but mutable applicant evidence has
    # no guaranteed historical copy; do not silently discard it on downgrade.
    connection = op.get_bind()
    if connection.exec_driver_sql("SELECT COUNT(*) FROM applicants WHERE experience_evidence IS NOT NULL AND experience_evidence != 'null'").scalar():
        raise RuntimeError('Cannot downgrade populated applicant experience evidence; restore a backup instead')
    with op.batch_alter_table('job_evaluations') as batch:
        batch.drop_column('queue_state')
    with op.batch_alter_table('applicants') as batch:
        batch.drop_column('experience_evidence')
