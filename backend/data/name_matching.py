"""Player-name normalization shared by keeper resolution and the retro harness.

Extracted from routes.py so scripts can reuse it without importing the API layer.
"""

from __future__ import annotations

import unicodedata

_SUFFIXES = (" jr.", " jr", " sr.", " sr", " ii", " iii", " iv")


def normalize_name(name: str) -> str:
    """Strip accents, lowercase, remove suffixes like Jr./III for matching."""
    # Decompose unicode and strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.lower().strip()
    # Remove common suffixes
    for suffix in _SUFFIXES:
        if ascii_name.endswith(suffix):
            ascii_name = ascii_name[: -len(suffix)].strip()
    return ascii_name
