"""Add email verification fields.

Revision ID: 0002_add_email_verification
Revises: 0001_initial
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_add_email_verification"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime()))


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
