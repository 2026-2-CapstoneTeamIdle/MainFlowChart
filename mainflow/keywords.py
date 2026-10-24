"""Keyword matching for classifying assets from their purpose/description text."""

from __future__ import annotations

import re
from collections.abc import Iterable


def has_keyword(text: str, keywords: Iterable[str]) -> bool:
    """Return True if any keyword occurs in lowercase ``text``.

    English keywords must stand alone as a word (an "s"/"es" plural is allowed), so
    "hit" does not match "white". Korean keywords match as substrings because
    particles attach directly to the word ("공격음", "공격을").
    """
    return any(
        re.search(rf"(?<![a-z]){re.escape(keyword)}(?:e?s)?(?![a-z])", text) for keyword in keywords
    )
