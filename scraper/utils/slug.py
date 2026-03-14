"""Slugify exercise names for safe filenames."""

import re
import unicodedata


def slugify(text: str, max_length: int = 80) -> str:
    """Convert text to a filesystem-safe slug (lowercase, hyphens, no spaces)."""
    if not text or not text.strip():
        return "unnamed"
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    text = text.strip("-")
    return text[:max_length] if text else "unnamed"
