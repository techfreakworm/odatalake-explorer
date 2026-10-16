"""Small shared types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Passage:
    """One numbered context passage sent to the LLM.

    n is its 1-based number in the prompt; `urls` go into `sources` when it is cited: doc_url for most chunks,
    up to two cite_urls for a fact card, the branch or SHA form for repo chunks.
    """

    n: int
    chunk: Mapping[str, Any]
    source_url: str
    score: float = 0.0
    source_urls: tuple[str, ...] = ()  # a fact card can contribute several cite_urls; source_url is the first

    @property
    def urls(self) -> tuple[str, ...]:
        return self.source_urls or (self.source_url,)
