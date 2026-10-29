"""
Utility functions for the Ruff application.
"""

import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from flask import current_app

DEFAULT_PREVIEW_LENGTH = 100


def utcnow() -> datetime:
    """
    Current UTC time as a naive datetime.

    Replaces the deprecated datetime.utcnow(). Kept naive because the
    DateTime columns store naive UTC values.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_preview_length(default: int = DEFAULT_PREVIEW_LENGTH) -> int:
    """Read preview length from app config when available."""
    try:
        return int(current_app.config.get("PREVIEW_LENGTH", default))
    except RuntimeError:
        # No app context active
        return default


def generate_stash_preview(body: str, preview_length: Optional[int] = None) -> str:
    """
    Generate a preview of stash body.

    Args:
        body: The full stash body
        preview_length: Maximum number of characters in preview (optional)

    Returns:
        Preview string with ellipsis if body is longer than preview_length
    """
    if preview_length is None:
        preview_length = _get_preview_length()
    if len(body) > preview_length:
        return body[:preview_length] + "..."
    return body


# The sheet ---------------------------------------------------------------------
# A stash is one plain-text sheet. Its first non-empty line is the title, and
# lines like "[ ] buy milk" / "[x] done" form the Recess Roster (task list).

ROSTER_PREFIX_RE = re.compile(r"^\s*(?:[-*]\s+)?\[( |x|X)\]\s?")
TITLE_MAX_LENGTH = 200


def roster_items(text: str) -> List[Dict]:
    """Recess Roster tasks in the sheet, in order."""
    items = []
    for line in (text or "").splitlines():
        match = ROSTER_PREFIX_RE.match(line)
        if match:
            task = line[match.end():].strip()
            if task:
                items.append({"text": task, "done": match.group(1) in "xX"})
    return items


def sheet_title(text: str) -> Optional[str]:
    """First non-empty line, without a roster box or markdown heading marks."""
    for line in (text or "").splitlines():
        line = ROSTER_PREFIX_RE.sub("", line).lstrip("#").strip()
        if line:
            return line[:TITLE_MAX_LENGTH]
    return None


def sheet_preview(text: str, preview_length: Optional[int] = None) -> str:
    """Preview of the sheet after its title line, without roster tasks."""
    lines = [line.strip() for line in (text or "").splitlines()]
    non_empty = [line for line in lines if line]
    prose = [line for line in non_empty[1:] if not ROSTER_PREFIX_RE.match(line)]
    rest = " ".join(prose) or (non_empty[0] if non_empty else "")
    return generate_stash_preview(rest, preview_length)


def compose_sheet(body: str, title: Optional[str] = None, checklist=None) -> str:
    """
    Build sheet text from the old separate fields (title, body, checklist), as
    used by imports, shares and data created before the sheet existed.
    """
    body = (body or "").strip("\n")
    parts = []
    if title and title.strip() and sheet_title(body) != title.strip():
        parts.append(title.strip())
    if body:
        parts.append(body)
    lines = []
    for item in checklist or []:
        if isinstance(item, dict):
            text, done = str(item.get("text", "")).strip(), bool(item.get("done"))
        else:
            text, done = str(item).strip(), False
        if text:
            lines.append(f"[{'x' if done else ' '}] {text}")
    existing = {(i["text"], i["done"]) for i in roster_items(body)}
    lines = [l for l in lines if (l[4:], l[1] == "x") not in existing]
    if lines:
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def time_ago(moment: datetime, now: Optional[datetime] = None) -> str:
    """Friendly relative time for naive-UTC datetimes ("2 days ago")."""
    now = now or utcnow()
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    for unit, size in (("minute", 60), ("hour", 3600), ("day", 86400)):
        next_size = {"minute": 3600, "hour": 86400, "day": 7 * 86400}[unit]
        if seconds < next_size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    if moment.year == now.year:
        return moment.strftime("%b %-d") if os.name != "nt" else moment.strftime("%b %#d")
    return moment.strftime("%b %Y")
