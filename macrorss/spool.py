"""Power-loss-tolerant segmented local spool."""

from __future__ import annotations

import json
import os
import time
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO

from macrorss.codec import observation_from_json
from macrorss.models import ObservationRecord


class SegmentedSpool:
    def __init__(
        self,
        directory: str | Path,
        *,
        segment_bytes: int = 4 * 1024 * 1024,
        max_age_seconds: float = 2.0,
        fsync_every: int = 1,
        archive_hours: float = 48.0,
    ) -> None:
        if segment_bytes < 1024:
            raise ValueError("segment_bytes must be >= 1024")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0")
        if fsync_every < 1:
            raise ValueError("fsync_every must be >= 1")
        self.directory = Path(directory)
        self.archive_dir = self.directory / "archive"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.segment_bytes = segment_bytes
        self.max_age_seconds = max_age_seconds
        self.fsync_every = fsync_every
        self.archive_hours = archive_hours
        self._handle: IO[bytes] | None = None
        self._path: Path | None = None
        self._opened_mono: float | None = None
        self._since_fsync = 0
        self._lock = threading.RLock()
        self.recover_open_segments()

    def _next_sequence(self) -> int:
        maximum = 0
        for root in (self.directory, self.archive_dir):
            for path in root.glob("[0-9]*.*"):
                try:
                    maximum = max(maximum, int(path.name.split(".", 1)[0]))
                except ValueError:
                    continue
        return maximum + 1

    def _ensure_open(self) -> None:
        if self._handle is not None:
            return
        sequence = self._next_sequence()
        self._path = self.directory / f"{sequence:012d}.open"
        self._handle = self._path.open("ab", buffering=0)
        self._opened_mono = time.monotonic()
        self._since_fsync = 0

    def append(self, record: ObservationRecord) -> Path:
        with self._lock:
            self._ensure_open()
            assert self._path is not None
            assert self._handle is not None
            line = json.dumps(record.to_json(), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            # Binary/unbuffered: write enters the kernel immediately; fsync defines durability.
            self._handle.write(line)
            self._since_fsync += 1
            if self._since_fsync >= self.fsync_every:
                os.fsync(self._handle.fileno())
                self._since_fsync = 0
            if self._path.stat().st_size >= self.segment_bytes:
                sealed = self.seal()
                assert sealed is not None
                return sealed
            return self._path

    def seal_if_due(self) -> Path | None:
        with self._lock:
            if self._handle is None or self._opened_mono is None:
                return None
            if time.monotonic() - self._opened_mono < self.max_age_seconds:
                return None
            return self.seal()

    def seal(self) -> Path | None:
        with self._lock:
            if self._handle is None or self._path is None:
                return None
            path = self._path
            os.fsync(self._handle.fileno())
            self._handle.close()
            ready = path.with_suffix(".ready")
            os.replace(path, ready)
            _fsync_dir(self.directory)
            self._handle = None
            self._path = None
            self._opened_mono = None
            self._since_fsync = 0
            return ready

    def close(self) -> Path | None:
        return self.seal()

    def ready_segments(self) -> list[Path]:
        with self._lock:
            return sorted(self.directory.glob("*.ready"))

    def read_segment(self, path: Path) -> list[ObservationRecord]:
        records: list[ObservationRecord] = []
        with path.open("rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.endswith(b"\n"):
                    raise ValueError(f"partial record in ready segment {path}:{line_number}")
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ValueError(f"invalid record in {path}:{line_number}")
                records.append(observation_from_json(payload))
        return records

    def archive(self, path: Path) -> Path:
        with self._lock:
            target = self.archive_dir / path.name.replace(".ready", ".done")
            os.replace(path, target)
            _fsync_dir(self.directory)
            _fsync_dir(self.archive_dir)
            return target

    def recover_open_segments(self) -> None:
        """Trim only a torn final JSON line and seal pre-existing open segments."""
        for path in sorted(self.directory.glob("*.open")):
            with path.open("r+b") as handle:
                data = handle.read()
                if data and not data.endswith(b"\n"):
                    cut = data.rfind(b"\n")
                    new_size = 0 if cut < 0 else cut + 1
                    handle.truncate(new_size)
                    handle.flush()
                    os.fsync(handle.fileno())
            if path.stat().st_size == 0:
                path.unlink(missing_ok=True)
                continue
            ready = path.with_suffix(".ready")
            os.replace(path, ready)
        _fsync_dir(self.directory)

    def seed_keys(self) -> tuple[set[str], set[str], set[str]]:
        """Return recent durable document/event/alert keys for restart-safe dedup."""
        documents: set[str] = set()
        events: set[str] = set()
        alerts: set[str] = set()
        paths = list(self.ready_segments()) + sorted(self.archive_dir.glob("*.done"))
        for path in paths:
            try:
                records = self.read_segment(path)
            except ValueError:
                continue
            for record in records:
                documents.add(f"{record.raw.source_id}:{record.raw.guid_hash}")
                events.add(record.event.event_fingerprint)
                if record.emitted:
                    alerts.add(record.event.event_fingerprint)
        return documents, events, alerts

    def prune_archive(self, now: float | None = None) -> int:
        with self._lock:
            if self.archive_hours <= 0:
                return 0
            now = now if now is not None else time.time()
            threshold = now - self.archive_hours * 3600.0
            removed = 0
            for path in self.archive_dir.glob("*.done"):
                try:
                    if path.stat().st_mtime < threshold:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
            return removed

    def status(self) -> dict[str, int | float | None]:
        with self._lock:
            ready = sorted(self.directory.glob("*.ready"))
            archived = list(self.archive_dir.glob("*.done"))
            open_files = list(self.directory.glob("*.open"))
            ready_bytes = sum(path.stat().st_size for path in ready if path.exists())
            oldest = min((path.stat().st_mtime for path in ready if path.exists()), default=None)
            age = None if oldest is None else max(0.0, time.time() - oldest)
            return {
                "ready_segments": len(ready),
                "open_segments": len(open_files) + (1 if self._path and self._path not in open_files else 0),
                "archive_segments": len(archived),
                "ready_bytes": ready_bytes,
                "oldest_ready_age_seconds": age,
            }

    def iter_all_records(self) -> Iterator[ObservationRecord]:
        paths: Iterable[Path] = [*self.ready_segments(), *sorted(self.archive_dir.glob("*.done"))]
        for path in paths:
            yield from self.read_segment(path)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
