"""
Utility functions for the Ruff application.
"""

from datetime import datetime
from typing import Dict, Any


def generate_stash_preview(text: str, preview_length: int = 50) -> str:
    """
    Generate a preview of stash text.

    Args:
        text: The full stash text
        preview_length: Maximum number of characters in preview
        
    Returns:
        Preview string with ellipsis if text is longer than preview_length
    """
    if len(text) > preview_length:
        return text[:preview_length] + "..."
    return text


def get_current_timestamp() -> str:
    """
    Get current timestamp in standardized format.

    Returns:
        Timestamp string in format 'YYYY-MM-DD HH:MM:SS'
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_stash_dict(stash_id: str, text: str) -> Dict[str, Any]:
    """
    Create a stash dictionary with all required fields.

    Args:
        stash_id: Unique identifier for the stash
        text: The stash content
        
    Returns:
        Dictionary containing stash data
    """
    return {
        "id": stash_id,
        "text": text,
        "created_at": get_current_timestamp(),
        "preview": generate_stash_preview(text),
    }


def sanitize_stash_data(stash: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure stash has all required fields (for backward compatibility).

    Args:
        stash: Stash dictionary to sanitize
        
    Returns:
        Stash dictionary with all required fields
    """
    if "preview" not in stash:
        stash["preview"] = generate_stash_preview(stash.get("text", ""))
    if "created_at" not in stash:
        stash["created_at"] = "N/A"
    return stash
