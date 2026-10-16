"""Small shared types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Passage:
    """One numbered context passage sent to the LLM.

    n is its 1-based number in the prompt; source_url is the URL that goes into `sources` when it is cited
    (doc_url for most chunks, one chosen cite_url for a fact card, branch or SHA form for repo chunks).
    """

    n: int
    chunk: Mapping[str, Any]
    source_url: str
    score: float = 0.0
