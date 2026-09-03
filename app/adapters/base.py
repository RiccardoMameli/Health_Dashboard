"""Adapter contract.

Every source implements the same two-method interface so the sync scheduler,
the Data Health screen and the tests never need to special-case a provider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as Date

from sqlalchemy.orm import Session


@dataclass
class SyncResult:
    source: str
    records_ingested: int = 0
    records_skipped: int = 0
    notes: list[str] = field(default_factory=list)


class Adapter(ABC):
    source: str

    @abstractmethod
    def backfill(self, session: Session, *, since: Date | None = None) -> SyncResult:
        """One-off deep history import."""

    @abstractmethod
    def incremental(self, session: Session) -> SyncResult:
        """Routine pull of whatever is new since the last successful run."""
