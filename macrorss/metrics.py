"""Lightweight in-process metrics and atomically published status snapshots."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Metrics:
    def __init__(self, path: str | Path, sample_capacity: int = 20_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.counters: dict[str, int] = defaultdict(int)
        self.samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=sample_capacity))
        self.source: dict[str, dict[str, Any]] = defaultdict(dict)
        self.started_at = datetime.now(UTC)

    def inc(self, key: str, amount: int = 1) -> None:
        self.counters[key] += amount

    def observe(self, key: str, value: float) -> None:
        if math.isfinite(value):
            self.samples[key].append(float(value))

    def source_update(self, source_id: str, **values: Any) -> None:
        self.source[source_id].update(values)

    def percentile(self, key: str, p: float) -> float | None:
        values = sorted(self.samples.get(key, ()))
        if not values:
            return None
        index = min(len(values) - 1, max(0, math.ceil((p / 100.0) * len(values)) - 1))
        return values[index]

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        uptime_seconds = max(0.001, (now - self.started_at).total_seconds())
        latency = {
            key: {
                "count": len(values),
                "p50": self.percentile(key, 50),
                "p99": self.percentile(key, 99),
            }
            for key, values in self.samples.items()
        }
        source_rates: dict[str, dict[str, float]] = {}
        for key, value in self.counters.items():
            if key.startswith("requests__"):
                source_id = key.removeprefix("requests__")
                source_rates.setdefault(source_id, {})["requests_per_minute"] = value * 60.0 / uptime_seconds
            elif key.startswith("items__"):
                source_id = key.removeprefix("items__")
                source_rates.setdefault(source_id, {})["items_per_day"] = value * 86400.0 / uptime_seconds
        http_requests = self.counters.get("http_requests", 0)
        ratio = self.counters.get("http_status_304", 0) / http_requests if http_requests else None
        return {
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "uptime_seconds": uptime_seconds,
            "http_304_ratio": ratio,
            "counters": dict(self.counters),
            "rates": source_rates,
            "latency_ms": latency,
            "sources": dict(self.source),
        }

    def publish(self) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(self.snapshot(), handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
