"""One shared search policy and editable tier strategies per applicant."""
from alembic import op
import sqlalchemy as sa

revision = '20260918_17'
down_revision = '20260917_16'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('search_policies',
        sa.Column('applicant_id', sa.Integer(), sa.ForeignKey('applicants.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('revision >= 1', name='ck_policy_revision'))
    op.create_table('tier_strategies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('applicant_id', sa.Integer(), sa.ForeignKey('search_policies.applicant_id'), nullable=False),
        sa.Column('tier', sa.String(1), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('applicant_id', 'tier', name='uq_applicant_tier'),
        sa.CheckConstraint("tier IN ('A','B','C','D')", name='ck_strategy_tier'))


def downgrade():
    op.drop_table('tier_strategies')
    op.drop_table('search_policies')
