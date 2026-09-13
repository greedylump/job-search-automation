"""Initial schema

Revision ID: 20260912_01
Revises: 
Create Date: 2026-09-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by alembic.
revision = "20260912_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_job_id", sa.String(length=128), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("remote_type", sa.String(length=64), nullable=True),
        sa.Column("employment_type", sa.String(length=64), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("salary_currency", sa.String(length=16), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("job_url", sa.String(length=512), nullable=True),
        sa.Column("apply_url", sa.String(length=512), nullable=True),
        sa.Column("ats_type", sa.String(length=64), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_source"), "jobs", ["source"], unique=False)
    op.create_index(op.f("ix_jobs_source_job_id"), "jobs", ["source_job_id"], unique=False)

    op.create_table(
        "job_evaluations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=True),
        sa.Column("hireability_score", sa.Float(), nullable=True),
        sa.Column("career_value_score", sa.Float(), nullable=True),
        sa.Column("income_value_score", sa.Float(), nullable=True),
        sa.Column("application_friction_score", sa.Float(), nullable=True),
        sa.Column("recommended_resume_variant", sa.String(length=64), nullable=True),
        sa.Column("tailoring_level", sa.String(length=32), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("estimated_ai_cost", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_evaluations_job_id"), "job_evaluations", ["job_id"], unique=False)

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("resume_variant", sa.String(length=64), nullable=True),
        sa.Column("tailoring_level", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_minutes", sa.Integer(), nullable=True),
        sa.Column("response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_applications_job_id"), "applications", ["job_id"], unique=False)

    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("jobs_seen", sa.Integer(), nullable=False),
        sa.Column("jobs_new", sa.Integer(), nullable=False),
        sa.Column("jobs_deduplicated", sa.Integer(), nullable=False),
        sa.Column("jobs_filtered", sa.Integer(), nullable=False),
        sa.Column("jobs_scored", sa.Integer(), nullable=False),
        sa.Column("ai_cost", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_job_id"), table_name="applications")
    op.drop_index(op.f("ix_job_evaluations_job_id"), table_name="job_evaluations")
    op.drop_index(op.f("ix_jobs_source_job_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_source"), table_name="jobs")
    op.drop_table("applications")
    op.drop_table("job_evaluations")
    op.drop_table("processing_runs")
    op.drop_table("jobs")
