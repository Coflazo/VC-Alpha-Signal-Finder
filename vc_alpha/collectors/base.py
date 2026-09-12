"""The contract every source implements.

Substack, Reddit and LinkedIn are all the same shape: a graph of nodes you visit,
each yielding candidates and pointing at neighbours. Keeping that contract narrow
is what lets frontier.py drive all three without knowing anything about them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Protocol


@dataclass(slots=True)
class CandidateRecord:
    """One discovered thing. Every collector yields these and nothing else."""

    source: str
    source_url: str
    raw_text: str
    title: str | None = None
    author: str | None = None
    node: str | None = None
    posted_at: str | None = None

    @property
    def id(self) -> str:
        return hashlib.sha256(self.source_url.encode()).hexdigest()


@dataclass(slots=True)
class Neighbour:
    """A graph edge: somewhere the frontier could go next."""

    node: str
    display_name: str | None = None


@dataclass(slots=True)
class Visit:
    """What one node visit produced."""

    candidates: list[CandidateRecord] = field(default_factory=list)
    neighbours: list[Neighbour] = field(default_factory=list)
    # True when the node has no more to give and should stop being revisited.
    exhausted: bool = False


class Collector(Protocol):
    """A source. Implementations live in this package, one file each."""

    source: str

    def visit(self, node: str) -> Visit:
        """Fetch one node: its candidates and the neighbours it points at."""
        ...

    def seeds(self) -> Iterable[Neighbour]:
        """Where to start when the frontier is empty."""
        ...
