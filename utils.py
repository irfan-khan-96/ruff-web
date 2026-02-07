"""
Utility functions for the Ruff application.
"""

from typing import Optional

from flask import current_app

DEFAULT_PREVIEW_LENGTH = 100


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
