"""Add relay sessions and entries.

Revision ID: 0004_add_relay_sessions
Revises: 0003_add_title_body_checklist
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_relay_sessions"
down_revision = "0003_add_title_body_checklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relay_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_entries", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_relay_sessions_code", "relay_sessions", ["code"], unique=True)

    op.create_table(
        "relay_entries",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("author_name", sa.String(length=80), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["relay_sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_relay_entries_session_id", "relay_entries", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_relay_entries_session_id", table_name="relay_entries")
    op.drop_table("relay_entries")
    op.drop_index("ix_relay_sessions_code", table_name="relay_sessions")
    op.drop_table("relay_sessions")
