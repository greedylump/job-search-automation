"""Add unique index for source + source_job_id on jobs.

Revision ID: 20260912_02
Revises: 20260912_01
Create Date: 2026-09-12 00:00:00.000000

"""
from alembic import op


revision = "20260912_02"
down_revision = "20260912_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_jobs_source_source_job_id",
        "jobs",
        ["source", "source_job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_source_source_job_id", table_name="jobs")
