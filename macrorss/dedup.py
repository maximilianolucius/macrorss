"""Bounded in-memory deduplication with durable seeding from spool/archive."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable


class BoundedSeenSet:
    def __init__(self, capacity: int = 100_000) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._items: OrderedDict[str, None] = OrderedDict()

    def add(self, key: str) -> bool:
        """Return True only when *key* was not already present."""
        if key in self._items:
            self._items.move_to_end(key)
            return False
        self._items[key] = None
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)
        return True

    def seed(self, keys: Iterable[str]) -> None:
        for key in keys:
            self.add(key)

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)


class Deduplicator:
    def __init__(
        self,
        document_capacity: int = 200_000,
        event_capacity: int = 100_000,
        alert_capacity: int = 100_000,
    ) -> None:
        self.documents = BoundedSeenSet(document_capacity)
        self.events = BoundedSeenSet(event_capacity)
        self.alerts = BoundedSeenSet(alert_capacity)

    def is_new_document(self, source_id: str, guid_hash: str) -> bool:
        return self.documents.add(f"{source_id}:{guid_hash}")

    def is_new_event(self, fingerprint: str) -> bool:
        return self.events.add(fingerprint)

    def already_alerted(self, fingerprint: str) -> bool:
        return fingerprint in self.alerts

    def mark_alerted(self, fingerprint: str) -> None:
        self.alerts.add(fingerprint)
