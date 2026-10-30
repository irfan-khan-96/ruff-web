"""Passwordless sign-in, local-first sync and folded notes.

- users.login_nonce: single-use secret embedded in the current email sign-in
  link (rotated on every request and on use).
- users.session_epoch: bumped by "sign out everywhere"; sessions carry a
  fingerprint of it.
- users.password_hash becomes optional (passwords are no longer used).
- stashes.synced_at: server time of the last write, the sync cursor.
- stash_tombstones: deleted stash ids, so deletions reach other devices.
- folded_notes: end-to-end encrypted, open-once notes (ciphertext only).

Revision ID: 0006_passwordless_sync_folded
Revises: 0005_single_sheet
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_passwordless_sync_folded"
down_revision = "0005_single_sheet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("login_nonce", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"))
        batch.alter_column("password_hash", existing_type=sa.String(length=255), nullable=True)

    with op.batch_alter_table("stashes") as batch:
        batch.add_column(sa.Column("synced_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE stashes SET synced_at = updated_at")
    with op.batch_alter_table("stashes") as batch:
        batch.alter_column("synced_at", existing_type=sa.DateTime(), nullable=False)
        batch.create_index("ix_stashes_user_synced", ["user_id", "synced_at"])

    op.create_table(
        "stash_tombstones",
        sa.Column("stash_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stash_tombstones_user_deleted", "stash_tombstones", ["user_id", "deleted_at"])

    op.create_table(
        "folded_notes",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("iv", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_folded_notes_expires_at", "folded_notes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_folded_notes_expires_at", table_name="folded_notes")
    op.drop_table("folded_notes")
    op.drop_index("ix_stash_tombstones_user_deleted", table_name="stash_tombstones")
    op.drop_table("stash_tombstones")
    with op.batch_alter_table("stashes") as batch:
        batch.drop_index("ix_stashes_user_synced")
        batch.drop_column("synced_at")
    # Accounts created without a password get an unusable placeholder hash
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("password_hash", existing_type=sa.String(length=255), nullable=False)
        batch.drop_column("session_epoch")
        batch.drop_column("login_nonce")
