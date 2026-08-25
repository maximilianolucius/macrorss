"""Core immutable-ish domain models used across the MacroRSS pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Transport = Literal["rss", "atom", "html", "json"]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PollPolicy:
    base_seconds: float = 60.0
    pre_window_seconds: float = 5.0
    burst_seconds: float = 1.0
    post_window_seconds: float = 5.0
    pre_window_minutes: float = 5.0
    burst_lead_seconds: float = 30.0
    burst_lag_seconds: float = 120.0
    post_window_minutes: float = 10.0
    jitter_fraction: float = 0.10
    min_seconds: float = 1.0

    def validate(self) -> None:
        positive = {
            "base_seconds": self.base_seconds,
            "pre_window_seconds": self.pre_window_seconds,
            "burst_seconds": self.burst_seconds,
            "post_window_seconds": self.post_window_seconds,
            "min_seconds": self.min_seconds,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"poll.{name} must be > 0")
        if not 0 <= self.jitter_fraction <= 0.5:
            raise ValueError("poll.jitter_fraction must be between 0 and 0.5")


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    name: str
    url: str | None
    enabled: bool = True
    transport: Transport = "rss"
    parser: str = "feed"
    tags: tuple[str, ...] = ()
    rank_gold: int | None = None
    rank_fx: int | None = None
    priority: int = 100
    requires_user_agent: bool = False
    timeout_seconds: float = 15.0
    max_body_bytes: int = 5 * 1024 * 1024
    user_agent: str = "MacroRSS/0.1 (+https://github.com/maximilianolucius/macrorss)"
    poll: PollPolicy = field(default_factory=PollPolicy)
    notes: str = ""
    parser_options: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id or any(ch.isspace() for ch in self.id):
            raise ValueError("source id must be non-empty and contain no whitespace")
        if self.enabled and not self.url:
            raise ValueError(f"enabled source {self.id!r} requires url")
        if self.transport not in {"rss", "atom", "html", "json"}:
            raise ValueError(f"source {self.id}: unsupported transport {self.transport!r}")
        if self.max_body_bytes < 1024:
            raise ValueError(f"source {self.id}: max_body_bytes must be >= 1024")
        if self.rank_gold is not None and self.rank_gold < 1:
            raise ValueError(f"source {self.id}: rank_gold must be >= 1")
        if self.rank_fx is not None and self.rank_fx < 1:
            raise ValueError(f"source {self.id}: rank_fx must be >= 1")
        self.poll.validate()


@dataclass(slots=True)
class SourceState:
    source_id: str
    etag: str | None = None
    last_modified: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    consecutive_errors: int = 0
    last_status: int | None = None
    circuit_open_until: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "last_success_at": iso_utc(self.last_success_at),
            "last_attempt_at": iso_utc(self.last_attempt_at),
            "consecutive_errors": self.consecutive_errors,
            "last_status": self.last_status,
            "circuit_open_until": iso_utc(self.circuit_open_until),
        }


@dataclass(frozen=True, slots=True)
class RawItem:
    source_id: str
    guid: str | None
    guid_hash: str
    url: str | None
    title: str
    raw_published_at: str | None
    published_at: datetime | None
    first_seen_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = iso_utc(self.published_at)
        data["first_seen_at"] = iso_utc(self.first_seen_at)
        return data


@dataclass(frozen=True, slots=True)
class LatencyTrace:
    request_started_mono: float
    response_received_mono: float
    parsed_mono: float
    event_emitted_mono: float | None = None
    spooled_mono: float | None = None
    persisted_mono: float | None = None

    @property
    def network_fetch_ms(self) -> float:
        return max(0.0, (self.response_received_mono - self.request_started_mono) * 1000.0)

    @property
    def parse_ms(self) -> float:
        return max(0.0, (self.parsed_mono - self.response_received_mono) * 1000.0)

    @property
    def hot_path_ms(self) -> float | None:
        if self.event_emitted_mono is None:
            return None
        return max(0.0, (self.event_emitted_mono - self.response_received_mono) * 1000.0)

    @property
    def spool_ms(self) -> float | None:
        if self.spooled_mono is None:
            return None
        return max(0.0, (self.spooled_mono - self.response_received_mono) * 1000.0)

    @property
    def persist_ms(self) -> float | None:
        if self.persisted_mono is None:
            return None
        return max(0.0, (self.persisted_mono - self.response_received_mono) * 1000.0)


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    event_fingerprint: str
    canonical_url: str | None
    canonical_title: str
    institution: str
    event_type: str
    published_at: datetime | None
    first_seen_at: datetime
    first_source_id: str
    tags: tuple[str, ...]
    rank_gold: int | None
    rank_fx: int | None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = iso_utc(self.published_at)
        data["first_seen_at"] = iso_utc(self.first_seen_at)
        return data


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    raw: RawItem
    event: NormalizedEvent
    emitted: bool
    latencies: dict[str, float | None] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "raw": self.raw.to_json(),
            "event": self.event.to_json(),
            "emitted": self.emitted,
            "latencies": dict(self.latencies),
        }
