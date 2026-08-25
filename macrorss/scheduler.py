"""Adaptive polling scheduler driven by source policy and scheduled event windows."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from macrorss.models import SourceConfig


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    id: str
    at: datetime
    source_ids: tuple[str, ...]
    name: str = ""
    tags: tuple[str, ...] = ()


class EventCalendar:
    def __init__(self, events: list[ScheduledEvent] | None = None) -> None:
        self.events = sorted(events or [], key=lambda item: item.at)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EventCalendar":
        file_path = Path(path)
        if not file_path.exists():
            return cls([])
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("events config root must be a mapping")
        items = raw.get("events", [])
        if not isinstance(items, list):
            raise ValueError("events must be a list")
        events: list[ScheduledEvent] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"events[{index}] must be a mapping")
            at = _parse_utc(item.get("at"), f"events[{index}].at")
            source_ids_raw = item.get("source_ids", [])
            if not isinstance(source_ids_raw, list) or not all(isinstance(x, str) for x in source_ids_raw):
                raise ValueError(f"events[{index}].source_ids must be list[str]")
            tags_raw = item.get("tags", [])
            if not isinstance(tags_raw, list) or not all(isinstance(x, str) for x in tags_raw):
                raise ValueError(f"events[{index}].tags must be list[str]")
            event_id = str(item.get("id", f"event-{index}"))
            if event_id in seen_ids:
                raise ValueError(f"duplicate scheduled event id: {event_id}")
            seen_ids.add(event_id)
            events.append(
                ScheduledEvent(
                    id=event_id,
                    at=at,
                    source_ids=tuple(source_ids_raw),
                    name=str(item.get("name", "")),
                    tags=tuple(tags_raw),
                )
            )
        return cls(events)

    def relevant(self, source_id: str, now: datetime) -> list[ScheduledEvent]:
        now = _aware_utc(now)
        horizon = timedelta(minutes=30)
        return [
            event
            for event in self.events
            if source_id in event.source_ids and abs(event.at - now) <= horizon
        ]


class AdaptiveScheduler:
    def __init__(self, calendar: EventCalendar, *, rng: random.Random | None = None) -> None:
        self.calendar = calendar
        self.rng = rng or random.Random()

    def interval(self, source: SourceConfig, now: datetime | None = None) -> float:
        now = _aware_utc(now or datetime.now(UTC))
        policy = source.poll
        interval = policy.base_seconds
        for event in self.calendar.relevant(source.id, now):
            delta = (event.at - now).total_seconds()
            if -policy.burst_lag_seconds <= delta <= policy.burst_lead_seconds:
                interval = min(interval, policy.burst_seconds)
            elif -policy.post_window_minutes * 60 <= delta < -policy.burst_lag_seconds:
                interval = min(interval, policy.post_window_seconds)
            elif policy.burst_lead_seconds < delta <= policy.pre_window_minutes * 60:
                interval = min(interval, policy.pre_window_seconds)
        interval = max(policy.min_seconds, interval)
        # Jitter only outside the most aggressive burst interval.
        if interval > policy.burst_seconds and policy.jitter_fraction:
            factor = 1.0 + self.rng.uniform(-policy.jitter_fraction, policy.jitter_fraction)
            interval = max(policy.min_seconds, interval * factor)
        return interval

    @staticmethod
    def backoff(source: SourceConfig, consecutive_errors: int) -> float:
        exponent = min(max(consecutive_errors - 1, 0), 7)
        return float(min(max(source.poll.base_seconds, 5.0) * (2**exponent), 900.0))


def _parse_utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{where} invalid datetime: {value}") from exc
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
