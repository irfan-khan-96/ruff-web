"""Passkeys: WebAuthn credentials for signing in without email.

Revision ID: 0007_passkeys
Revises: 0006_passwordless_sync_folded
Create Date: 2026-11-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_passkeys"
down_revision = "0006_passwordless_sync_folded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passkeys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", sa.String(length=512), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("credential_id"),
    )
    op.create_index("ix_passkeys_user_id", "passkeys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_passkeys_user_id", table_name="passkeys")
    op.drop_table("passkeys")
