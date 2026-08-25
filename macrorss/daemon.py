"""Async MacroRSS daemon orchestration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from datetime import timedelta
from typing import Any

import httpx

from macrorss.clock_health import ntp_synchronized
from macrorss.config import DatabaseConfig, RuntimeConfig, load_sources
from macrorss.dedup import Deduplicator
from macrorss.dispatcher import (
    Dispatcher,
    JsonlFileSink,
    StdoutJsonSink,
    TelegramSink,
    WebhookSink,
    ZeroMQSink,
)
from macrorss.fetcher import FetchError, HTTPStatusFetchError, HttpFetcher, NetworkFetchError
from macrorss.impact import ImpactFilter
from macrorss.logging_utils import configure_logging
from macrorss.metrics import Metrics
from macrorss.models import LatencyTrace, ObservationRecord, SourceConfig, SourceState, utcnow
from macrorss.normalizer import normalize_event
from macrorss.scheduler import AdaptiveScheduler, EventCalendar
from macrorss.sources import parser_for_source
from macrorss.spool import SegmentedSpool
from macrorss.state import LocalStateStore
from macrorss.store import MySQLStore, StoreUnavailable

log = logging.getLogger("macrorss.daemon")


class MacroRSSDaemon:
    def __init__(self, runtime: RuntimeConfig | None = None) -> None:
        self.runtime = runtime or RuntimeConfig.from_env()
        self.sources = [source for source in load_sources(self.runtime.config_path) if source.enabled]
        self.calendar = EventCalendar.from_yaml(self.runtime.events_path)
        self.scheduler = AdaptiveScheduler(self.calendar)
        self.fetcher = HttpFetcher()
        self.spool = SegmentedSpool(
            self.runtime.spool_dir,
            segment_bytes=self.runtime.spool_segment_bytes,
            max_age_seconds=self.runtime.spool_segment_max_age_seconds,
            fsync_every=self.runtime.spool_fsync_every,
            archive_hours=self.runtime.spool_archive_hours,
        )
        self.local_state = LocalStateStore(self.runtime.state_path)
        self.states = self.local_state.load()
        for source in self.sources:
            self.states.setdefault(source.id, SourceState(source_id=source.id))
        self.metrics = Metrics(self.runtime.metrics_path)
        self.dedup = Deduplicator()
        document_keys, event_keys, alert_keys = self.spool.seed_keys()
        self.dedup.documents.seed(document_keys)
        self.dedup.events.seed(event_keys)
        self.dedup.alerts.seed(alert_keys)
        self.event_first_source: dict[str, str] = {}
        self.impact_filter = ImpactFilter.from_env()
        self.emit_bootstrap = os.getenv("MACRORSS_EMIT_BOOTSTRAP", "0").lower() in {"1", "true", "yes"}
        self.stop_event = asyncio.Event()
        self.store: MySQLStore | None = self._build_store()
        self.dispatcher = Dispatcher(self._build_sinks(), queue_size=self.runtime.dispatcher_queue_size)
        self.tasks: list[asyncio.Task[None]] = []
        self._spool_warning_active = False
        self.network_recovered_event = asyncio.Event()
        self._network_issue_seen = False

    def _build_store(self) -> MySQLStore | None:
        try:
            config = DatabaseConfig.from_env(require_password=False)
        except ValueError as exc:
            log.warning("invalid database configuration; spool-only mode: %s", exc)
            return None
        if not config.password:
            log.warning("MACRORSS_DB_PASSWORD not set; spool-only mode")
            return None
        return MySQLStore(config)

    def _build_sinks(self) -> list[Any]:
        sinks: list[Any] = [StdoutJsonSink(), JsonlFileSink(self.runtime.event_log_path)]
        if self.runtime.zmq_bind:
            sinks.append(ZeroMQSink(self.runtime.zmq_bind))
        if self.runtime.webhook_url:
            sinks.append(WebhookSink(self.runtime.webhook_url))
        if self.runtime.telegram_bot_token and self.runtime.telegram_chat_id:
            sinks.append(TelegramSink(self.runtime.telegram_bot_token, self.runtime.telegram_chat_id))
        return sinks

    async def run(self) -> None:
        await self.dispatcher.start()
        await self._seed_from_mysql()
        self._install_signal_handlers()
        self.tasks = [
            asyncio.create_task(self._source_loop(source), name=f"source:{source.id}")
            for source in self.sources
        ]
        self.tasks.extend(
            [
                asyncio.create_task(self._flush_loop(), name="mysql-flusher"),
                asyncio.create_task(self._metrics_loop(), name="metrics"),
                asyncio.create_task(self._state_sync_loop(), name="state-sync"),
                asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
                asyncio.create_task(self._clock_loop(), name="clock-health"),
            ]
        )
        log.info("MacroRSS started with %d enabled sources", len(self.sources))
        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        self.stop_event.set()
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.tasks.clear()
        await asyncio.to_thread(self.spool.close)
        self.local_state.save(self.states)
        self.metrics.publish()
        await self.dispatcher.close()
        await self.fetcher.close()
        if self.store is not None:
            await self.store.close()
        log.info("MacroRSS stopped")

    def request_stop(self) -> None:
        self.stop_event.set()

    async def _seed_from_mysql(self) -> None:
        if self.store is None:
            return
        try:
            fingerprints = await self.store.recent_event_fingerprints(hours=72)
            alert_fingerprints = await self.store.recent_alert_fingerprints(hours=72)
        except StoreUnavailable as exc:
            self.metrics.inc("mysql_seed_errors")
            log.warning("MySQL unavailable at startup; durable spool seed remains active: %s", exc)
            return
        self.dedup.events.seed(fingerprints)
        self.dedup.alerts.seed(alert_fingerprints)
        self.metrics.inc("mysql_seeded_events", len(fingerprints))
        self.metrics.inc("mysql_seeded_alerts", len(alert_fingerprints))

    async def _source_loop(self, source: SourceConfig) -> None:
        state = self.states[source.id]
        parser = parser_for_source(source)
        while not self.stop_event.is_set():
            bootstrap = state.last_success_at is None
            now = utcnow()
            if state.circuit_open_until and now < state.circuit_open_until:
                await self._sleep_until_or_stop((state.circuit_open_until - now).total_seconds())
                continue
            state.last_attempt_at = now
            try:
                result = await self.fetcher.fetch(source, state)
            except HTTPStatusFetchError as exc:
                await self._record_failure(source, state, exc, status=exc.status_code)
                delay = exc.retry_after or self.scheduler.backoff(source, state.consecutive_errors)
                await self._sleep_until_or_stop(delay)
                continue
            except NetworkFetchError as exc:
                self.metrics.inc("network_errors")
                self._network_issue_seen = True
                await self._record_failure(source, state, exc, status=None, allow_circuit=False)
                await self._sleep_until_or_stop(
                    min(self.scheduler.backoff(source, state.consecutive_errors), 30.0),
                    wake_on_network=True,
                )
                continue
            except FetchError as exc:
                await self._record_failure(source, state, exc, status=None)
                await self._sleep_until_or_stop(self.scheduler.backoff(source, state.consecutive_errors))
                continue

            if self._network_issue_seen:
                self._network_issue_seen = False
                self.network_recovered_event.set()
                asyncio.get_running_loop().call_later(0.25, self.network_recovered_event.clear)
                self.metrics.inc("network_recoveries")
                log.info("network recovery observed; waking source loops for immediate re-fetch")

            state.etag = result.etag or state.etag
            state.last_modified = result.last_modified or state.last_modified
            state.last_status = result.status_code
            state.last_success_at = utcnow()
            state.consecutive_errors = 0
            state.circuit_open_until = None
            self.metrics.inc("http_requests")
            self.metrics.inc(f"requests__{source.id}")
            self.metrics.inc(f"http_status_{result.status_code}")
            self.metrics.inc(f"http_status__{source.id}__{result.status_code}")
            network_ms = (result.response_received_mono - result.request_started_mono) * 1000.0
            self.metrics.observe("network_fetch_ms", network_ms)
            self.metrics.observe(f"network_fetch_ms__{source.id}", network_ms)
            self.metrics.source_update(
                source.id,
                last_status=result.status_code,
                last_success_at=state.last_success_at.isoformat().replace("+00:00", "Z"),
                consecutive_errors=0,
                next_interval_seconds=self.scheduler.interval(source),
            )
            if result.changed:
                parsed_started = result.response_received_mono
                try:
                    raw_items = parser.parse(source, result.body, parsed_started)
                except Exception as exc:
                    self.metrics.inc("parse_errors")
                    log.exception("parser failed for %s: %s", source.id, exc, extra={"source_id": source.id})
                    await self._sleep_until_or_stop(self.scheduler.interval(source))
                    continue
                parsed_mono = time.monotonic()
                parse_ms = (parsed_mono - result.response_received_mono) * 1000.0
                self.metrics.observe("parse_ms", parse_ms)
                self.metrics.observe(f"parse_ms__{source.id}", parse_ms)
                self.metrics.inc("raw_items_seen", len(raw_items))
                self.metrics.inc(f"items__{source.id}", len(raw_items))
                self.metrics.source_update(source.id, last_item_count=len(raw_items))
                for raw in raw_items:
                    await self._process_item(
                        source,
                        raw,
                        bootstrap=bootstrap,
                        request_started=result.request_started_mono,
                        response_received=result.response_received_mono,
                        parsed_mono=parsed_mono,
                    )

            await asyncio.to_thread(self.local_state.save, self.states)
            await self._sleep_until_or_stop(self.scheduler.interval(source))

    async def _process_item(
        self,
        source: SourceConfig,
        raw: Any,
        *,
        bootstrap: bool,
        request_started: float,
        response_received: float,
        parsed_mono: float,
    ) -> None:
        if not self.dedup.is_new_document(raw.source_id, raw.guid_hash):
            self.metrics.inc("document_duplicates")
            return

        event = normalize_event(source, raw)
        is_new_event = self.dedup.is_new_event(event.event_fingerprint)
        if is_new_event:
            self.event_first_source[event.event_fingerprint] = source.id
            self.metrics.inc("normalized_events")
        else:
            first = self.event_first_source.get(event.event_fingerprint, "unknown")
            self.metrics.inc("cross_source_duplicates")
            self.metrics.inc(f"race__{_metric_key(first)}__then__{_metric_key(source.id)}")

        eligible = self.impact_filter.allows(event)
        suppress_bootstrap = bootstrap and not self.emit_bootstrap
        emitted = False
        emitted_mono: float | None = None
        if eligible and not suppress_bootstrap and not self.dedup.already_alerted(event.event_fingerprint):
            emitted = self.dispatcher.emit_nowait(event)
            if emitted:
                self.dedup.mark_alerted(event.event_fingerprint)
                emitted_mono = time.monotonic()
                self.metrics.inc("events_emitted")
                hot_ms = (emitted_mono - response_received) * 1000.0
                self.metrics.observe("hot_path_ms", hot_ms)
                self.metrics.observe(f"hot_path_ms__{source.id}", hot_ms)
            else:
                self.metrics.inc("dispatcher_dropped")

        trace = LatencyTrace(
            request_started_mono=request_started,
            response_received_mono=response_received,
            parsed_mono=parsed_mono,
            event_emitted_mono=emitted_mono,
        )
        record = ObservationRecord(
            raw=raw,
            event=event,
            emitted=emitted,
            latencies={
                "network_fetch_ms": trace.network_fetch_ms,
                "parse_ms": trace.parse_ms,
                "hot_path_ms": trace.hot_path_ms,
            },
        )
        spool_started = time.monotonic()
        await asyncio.to_thread(self.spool.append, record)
        spooled = time.monotonic()
        spool_ms = (spooled - response_received) * 1000.0
        self.metrics.observe("spool_ms", spool_ms)
        self.metrics.inc("records_spooled")
        if raw.published_at is not None:
            source_lag = (raw.first_seen_at - raw.published_at).total_seconds() * 1000.0
            self.metrics.observe("source_lag_ms", source_lag)
            self.metrics.observe(f"source_lag_ms__{source.id}", source_lag)
            if source_lag < -1000.0:
                self.metrics.inc("negative_source_lag")
        self.metrics.observe("spool_write_ms", (spooled - spool_started) * 1000.0)

    async def _record_failure(
        self,
        source: SourceConfig,
        state: SourceState,
        exc: Exception,
        *,
        status: int | None,
        allow_circuit: bool = True,
    ) -> None:
        state.last_status = status
        state.consecutive_errors += 1
        if allow_circuit and state.consecutive_errors >= 5:
            seconds = min(self.scheduler.backoff(source, state.consecutive_errors), 900.0)
            state.circuit_open_until = utcnow() + timedelta(seconds=seconds)
            self.metrics.inc("circuit_breaker_opens")
        self.metrics.inc("fetch_errors")
        self.metrics.source_update(
            source.id,
            last_status=status,
            consecutive_errors=state.consecutive_errors,
            error=str(exc),
        )
        await asyncio.to_thread(self.local_state.save, self.states)
        log.warning(
            "source fetch failed: %s",
            exc,
            extra={"source_id": source.id, "status_code": status, "error_count": state.consecutive_errors},
        )

    async def _flush_loop(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.to_thread(self.spool.seal_if_due)
            if self.store is not None:
                for path in self.spool.ready_segments():
                    try:
                        records = await asyncio.to_thread(self.spool.read_segment, path)
                        started = time.monotonic()
                        await self.store.persist_records(records)
                        elapsed = (time.monotonic() - started) * 1000.0
                        self.metrics.observe("mysql_flush_ms", elapsed)
                        self.metrics.inc("records_persisted", len(records))
                        await asyncio.to_thread(self.spool.archive, path)
                    except (StoreUnavailable, ValueError, OSError) as exc:
                        self.metrics.inc("mysql_flush_errors")
                        log.warning("spool flush deferred: %s", exc)
                        break
            await asyncio.to_thread(self.spool.prune_archive)
            await self._sleep_until_or_stop(self.runtime.flush_interval_seconds)

    async def _state_sync_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.store is not None:
                for state in list(self.states.values()):
                    try:
                        await self.store.upsert_feed_state(state)
                    except StoreUnavailable:
                        self.metrics.inc("mysql_state_sync_errors")
                        break
            await self._sleep_until_or_stop(10.0)

    async def _metrics_loop(self) -> None:
        while not self.stop_event.is_set():
            spool_status = await asyncio.to_thread(self.spool.status)
            for key, value in spool_status.items():
                if isinstance(value, (int, float)):
                    self.metrics.source_update("_spool", **{key: value})
            self.metrics.source_update("_dispatcher", queue_depth=self.dispatcher.queue.qsize())
            ready_bytes = int(spool_status.get("ready_bytes") or 0)
            oldest_age = float(spool_status.get("oldest_ready_age_seconds") or 0.0)
            warning = ready_bytes >= self.runtime.spool_warn_bytes or oldest_age >= self.runtime.spool_warn_age_seconds
            if warning and not self._spool_warning_active:
                log.warning("spool backlog warning: bytes=%d oldest_age_s=%.1f", ready_bytes, oldest_age)
                self.metrics.inc("spool_backlog_alerts")
            self._spool_warning_active = warning
            await asyncio.to_thread(self.metrics.publish)
            await self._sleep_until_or_stop(5.0)

    async def _heartbeat_loop(self) -> None:
        if not self.runtime.heartbeat_url:
            await self.stop_event.wait()
            return
        async with httpx.AsyncClient(timeout=5.0) as client:
            while not self.stop_event.is_set():
                try:
                    response = await client.get(self.runtime.heartbeat_url)
                    response.raise_for_status()
                    self.metrics.inc("heartbeat_ok")
                except httpx.HTTPError:
                    self.metrics.inc("heartbeat_errors")
                await self._sleep_until_or_stop(self.runtime.heartbeat_seconds)

    async def _clock_loop(self) -> None:
        while not self.stop_event.is_set():
            status = await asyncio.to_thread(ntp_synchronized)
            self.metrics.source_update("_clock", ntp_synchronized=status)
            if status is False:
                self.metrics.inc("clock_unsynchronized_checks")
                log.error("host clock is not NTP synchronized; latency timestamps are not trustworthy")
            await self._sleep_until_or_stop(self.runtime.ntp_check_seconds)

    async def _sleep_until_or_stop(self, seconds: float, *, wake_on_network: bool = False) -> None:
        timeout = max(0.01, seconds)
        if not wake_on_network:
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=timeout)
            except TimeoutError:
                return
            return

        stop_task = asyncio.create_task(self.stop_event.wait())
        network_task = asyncio.create_task(self.network_recovered_event.wait())
        try:
            done, pending = await asyncio.wait(
                {stop_task, network_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            del done
            for task in pending:
                task.cancel()
        finally:
            for task in (stop_task, network_task):
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signum, self.request_stop)


def _metric_key(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_") or "unknown"


async def run_daemon(runtime: RuntimeConfig | None = None) -> None:
    configure_logging(os.getenv("MACRORSS_LOG_LEVEL", "INFO"))
    daemon = MacroRSSDaemon(runtime)
    await daemon.run()
