"""Add Applicant model and nullable applicant links.

Revision ID: 20260912_04
Revises: 20260912_03
Create Date: 2026-09-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260912_04"
down_revision = "20260912_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applicants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("professional_summary", sa.Text(), nullable=True),
        sa.Column("experience_summary", sa.Text(), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("linkedin_url", sa.String(length=512), nullable=True),
        sa.Column("github_url", sa.String(length=512), nullable=True),
        sa.Column("portfolio_url", sa.String(length=512), nullable=True),
        sa.Column("target_roles", sa.JSON(), nullable=False),
        sa.Column("preferred_locations", sa.JSON(), nullable=False),
        sa.Column("remote_preference", sa.String(length=32), nullable=True),
        sa.Column("minimum_salary", sa.Float(), nullable=True),
        sa.Column("salary_currency", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_applicants_email"), "applicants", ["email"], unique=False)
    op.create_index(op.f("ix_applicants_full_name"), "applicants", ["full_name"], unique=False)

    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("applicant_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_applications_applicant_id"), ["applicant_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_applications_applicant_id_applicants",
            "applicants",
            ["applicant_id"],
            ["id"],
        )

    with op.batch_alter_table("job_evaluations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("applicant_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_job_evaluations_applicant_id"), ["applicant_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_job_evaluations_applicant_id_applicants",
            "applicants",
            ["applicant_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("job_evaluations", schema=None) as batch_op:
        batch_op.drop_constraint("fk_job_evaluations_applicant_id_applicants", type_="foreignkey")
        batch_op.drop_index(op.f("ix_job_evaluations_applicant_id"))
        batch_op.drop_column("applicant_id")

    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_constraint("fk_applications_applicant_id_applicants", type_="foreignkey")
        batch_op.drop_index(op.f("ix_applications_applicant_id"))
        batch_op.drop_column("applicant_id")

    op.drop_index(op.f("ix_applicants_full_name"), table_name="applicants")
    op.drop_index(op.f("ix_applicants_email"), table_name="applicants")
    op.drop_table("applicants")
