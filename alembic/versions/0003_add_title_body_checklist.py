"""Add title/body/checklist fields to stashes.

Revision ID: 0003_add_title_body_checklist
Revises: 0002_add_email_verification
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_add_title_body_checklist"
down_revision = "0002_add_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stashes") as batch:
        batch.add_column(sa.Column("title", sa.String(length=200)))
        batch.add_column(sa.Column("body", sa.Text()))
        batch.add_column(sa.Column("checklist", sa.Text()))

    op.execute("UPDATE stashes SET body = text")

    with op.batch_alter_table("stashes") as batch:
        batch.alter_column("body", nullable=False)
        batch.drop_column("text")


def downgrade() -> None:
    with op.batch_alter_table("stashes") as batch:
        batch.add_column(sa.Column("text", sa.Text(), nullable=True))

    op.execute("UPDATE stashes SET text = body")

    with op.batch_alter_table("stashes") as batch:
        batch.drop_column("checklist")
        batch.drop_column("body")
        batch.drop_column("title")
        batch.alter_column("text", nullable=False)
