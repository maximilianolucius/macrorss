"""Stable JSON codec for durable spool records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from macrorss.models import NormalizedEvent, ObservationRecord, RawItem


def observation_from_json(data: dict[str, Any]) -> ObservationRecord:
    raw_data = _mapping(data.get("raw"), "raw")
    event_data = _mapping(data.get("event"), "event")
    latencies = data.get("latencies", {})
    if not isinstance(latencies, dict):
        latencies = {}
    raw = RawItem(
        source_id=str(raw_data["source_id"]),
        guid=_optional_str(raw_data.get("guid")),
        guid_hash=str(raw_data["guid_hash"]),
        url=_optional_str(raw_data.get("url")),
        title=str(raw_data.get("title", "")),
        raw_published_at=_optional_str(raw_data.get("raw_published_at")),
        published_at=_dt(raw_data.get("published_at")),
        first_seen_at=_required_dt(raw_data.get("first_seen_at"), "raw.first_seen_at"),
        payload=_mapping(raw_data.get("payload", {}), "raw.payload"),
    )
    tags = event_data.get("tags", [])
    if not isinstance(tags, (list, tuple)):
        tags = []
    event = NormalizedEvent(
        event_fingerprint=str(event_data["event_fingerprint"]),
        canonical_url=_optional_str(event_data.get("canonical_url")),
        canonical_title=str(event_data.get("canonical_title", "")),
        institution=str(event_data.get("institution", "")),
        event_type=str(event_data.get("event_type", "macro_news")),
        published_at=_dt(event_data.get("published_at")),
        first_seen_at=_required_dt(event_data.get("first_seen_at"), "event.first_seen_at"),
        first_source_id=str(event_data.get("first_source_id", raw.source_id)),
        tags=tuple(str(tag) for tag in tags),
        rank_gold=_optional_int(event_data.get("rank_gold")),
        rank_fx=_optional_int(event_data.get("rank_fx")),
    )
    return ObservationRecord(
        raw=raw,
        event=event,
        emitted=bool(data.get("emitted", False)),
        latencies={str(k): _optional_float(v) for k, v in latencies.items()},
    )


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    return value


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("datetime must be string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_dt(value: Any, where: str) -> datetime:
    parsed = _dt(value)
    if parsed is None:
        raise ValueError(f"{where} is required")
    return parsed


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
