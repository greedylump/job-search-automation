"""Add processing run failure audit columns.

Revision ID: 20260912_03
Revises: 20260912_02
Create Date: 2026-09-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260912_03"
down_revision = "20260912_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_runs", sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"))
    op.add_column("processing_runs", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("processing_runs", "error_message")
    op.drop_column("processing_runs", "status")
