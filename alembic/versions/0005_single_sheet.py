"""Single sheet: fold titles and checklists into the text; collections become tags.

- Each stash's text becomes one sheet: its title as the first line, then the
  body, then its checklist as Recess Roster lines ("[ ] task" / "[x] task").
  title/preview/checklist columns are re-derived from that text.
- Each stash in a collection gets a tag with the collection's name.
- The collections table and stashes.collection_id are dropped.

Downgrade restores the empty table and column; collection membership is kept
as tags (nothing is lost, but stashes aren't moved back into collections).

Revision ID: 0005_single_sheet
Revises: 0004_add_relay_sessions
Create Date: 2026-10-29
"""

import json
import re

from alembic import op
import sqlalchemy as sa


revision = "0005_single_sheet"
down_revision = "0004_add_relay_sessions"
branch_labels = None
depends_on = None

# Kept local (not imported from the app) so this migration never changes
# behaviour when the app's helpers do
ROSTER_RE = re.compile(r"^\s*(?:[-*]\s+)?\[( |x|X)\]\s?")
PREVIEW_LENGTH = 100


def _title(text):
    for line in text.splitlines():
        line = ROSTER_RE.sub("", line).lstrip("#").strip()
        if line:
            return line[:200]
    return None


def _preview(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    prose = [line for line in lines[1:] if not ROSTER_RE.match(line)]
    rest = " ".join(prose) or (lines[0] if lines else "")
    return rest[:PREVIEW_LENGTH] + "..." if len(rest) > PREVIEW_LENGTH else rest


def _roster(text):
    items = []
    for line in text.splitlines():
        match = ROSTER_RE.match(line)
        if match and line[match.end():].strip():
            items.append({"text": line[match.end():].strip(), "done": match.group(1) in "xX"})
    return items


def _compose(title, body, checklist_json):
    body = (body or "").strip("\n")
    parts = []
    if title and title.strip() and _title(body) != title.strip():
        parts.append(title.strip())
    if body:
        parts.append(body)
    try:
        checklist = json.loads(checklist_json) if checklist_json else []
    except ValueError:
        checklist = []
    lines = []
    for item in checklist if isinstance(checklist, list) else []:
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            lines.append(f"[{'x' if item.get('done') else ' '}] {str(item['text']).strip()}")
    if lines:
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def upgrade() -> None:
    conn = op.get_bind()
    stashes = sa.table(
        "stashes",
        sa.column("id", sa.String), sa.column("title", sa.String), sa.column("body", sa.Text),
        sa.column("checklist", sa.Text), sa.column("preview", sa.String),
        sa.column("collection_id", sa.Integer),
    )
    tags = sa.table("tags", sa.column("id", sa.Integer), sa.column("name", sa.String),
                    sa.column("created_at", sa.DateTime))
    stash_tags = sa.table("stash_tags", sa.column("stash_id", sa.String), sa.column("tag_id", sa.Integer))
    collections = sa.table("collections", sa.column("id", sa.Integer), sa.column("name", sa.String))

    # 1. One sheet per stash
    for row in conn.execute(sa.select(stashes.c.id, stashes.c.title, stashes.c.body, stashes.c.checklist)).fetchall():
        text = _compose(row.title, row.body, row.checklist)
        roster = _roster(text)
        conn.execute(stashes.update().where(stashes.c.id == row.id).values(
            body=text, title=_title(text), preview=_preview(text),
            checklist=json.dumps(roster) if roster else None,
        ))

    # 2. Collections become tags
    names = {r.id: r.name for r in conn.execute(sa.select(collections.c.id, collections.c.name))}
    for row in conn.execute(sa.select(stashes.c.id, stashes.c.collection_id)
                            .where(stashes.c.collection_id.isnot(None))).fetchall():
        name = (names.get(row.collection_id) or "").strip().lower()[:50]
        if not name:
            continue
        tag_id = conn.execute(sa.select(tags.c.id).where(tags.c.name == name)).scalar()
        if tag_id is None:
            conn.execute(tags.insert().values(name=name, created_at=sa.func.now()))
            tag_id = conn.execute(sa.select(tags.c.id).where(tags.c.name == name)).scalar()
        exists = conn.execute(sa.select(stash_tags.c.tag_id).where(
            (stash_tags.c.stash_id == row.id) & (stash_tags.c.tag_id == tag_id))).first()
        if not exists:
            conn.execute(stash_tags.insert().values(stash_id=row.id, tag_id=tag_id))

    # 3. Drop collections
    with op.batch_alter_table("stashes") as batch:
        batch.drop_column("collection_id")
    op.drop_table("collections")


def downgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_user_collection_name"),
    )
    with op.batch_alter_table("stashes") as batch:
        batch.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
