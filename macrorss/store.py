"""Async MySQL durable store.

MySQL is intentionally outside the alert hot path.  This module can be unavailable
without preventing fetch/parse/emit/spool.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from macrorss.config import DatabaseConfig
from macrorss.models import ObservationRecord, SourceState

REQUIRED_TABLES = {
    "schema_meta",
    "raw_items",
    "events",
    "event_observations",
    "feed_state",
    "deliveries",
}


class StoreUnavailable(RuntimeError):
    pass


class MySQLStore:
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self.pool: Any = None

    async def connect(self) -> None:
        if self.pool is not None:
            return
        try:
            import asyncmy
        except ModuleNotFoundError as exc:
            raise StoreUnavailable("asyncmy is not installed; install project dependencies") from exc
        try:
            self.pool = await asyncmy.create_pool(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                db=self.config.name,
                charset="utf8mb4",
                autocommit=False,
                minsize=self.config.minsize,
                maxsize=self.config.maxsize,
                connect_timeout=self.config.connect_timeout,
                init_command="SET time_zone = '+00:00'",
            )
        except Exception as exc:
            raise StoreUnavailable(f"cannot connect to MySQL {self.config.host}:{self.config.port}: {exc}") from exc

    async def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None

    async def check_schema(self) -> dict[str, Any]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await _ping(conn)
            async with conn.cursor() as cursor:
                await cursor.execute("SHOW TABLES")
                rows = await cursor.fetchall()
                present = {str(row[0]) for row in rows}
                missing = sorted(REQUIRED_TABLES - present)
                await cursor.execute("SELECT @@innodb_flush_log_at_trx_commit, @@time_zone")
                durability, timezone = await cursor.fetchone()
                if missing:
                    raise StoreUnavailable(f"schema incomplete; missing tables: {', '.join(missing)}")
                return {
                    "tables": sorted(present),
                    "innodb_flush_log_at_trx_commit": int(durability),
                    "time_zone": str(timezone),
                }

    async def persist_records(self, records: Sequence[ObservationRecord]) -> int:
        if not records:
            return 0
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await _ping(conn)
            try:
                async with conn.cursor() as cursor:
                    for record in records:
                        raw_id = await self._upsert_raw(cursor, record)
                        event_id = await self._upsert_event(cursor, record)
                        await cursor.execute(
                            """
                            INSERT INTO event_observations (event_id, raw_item_id, observed_at)
                            VALUES (%s, %s, %s) AS newrow
                            ON DUPLICATE KEY UPDATE observed_at = LEAST(event_observations.observed_at, newrow.observed_at)
                            """,
                            (event_id, raw_id, _mysql_dt(record.raw.first_seen_at)),
                        )
                    await conn.commit()
            except Exception as exc:
                await conn.rollback()
                raise StoreUnavailable(f"MySQL transaction failed: {exc}") from exc
        return len(records)

    async def _upsert_raw(self, cursor: Any, record: ObservationRecord) -> int:
        raw = record.raw
        await cursor.execute(
            """
            INSERT INTO raw_items
                (source_id, guid_hash, guid, url, title, raw_published_at, published_at,
                 first_seen_at, payload_json)
            VALUES (%s, UNHEX(%s), %s, %s, %s, %s, %s, %s, %s) AS newrow
            ON DUPLICATE KEY UPDATE
                id = LAST_INSERT_ID(id),
                first_seen_at = LEAST(raw_items.first_seen_at, newrow.first_seen_at),
                payload_json = newrow.payload_json
            """,
            (
                raw.source_id,
                raw.guid_hash,
                raw.guid,
                raw.url,
                raw.title,
                raw.raw_published_at,
                _mysql_dt(raw.published_at),
                _mysql_dt(raw.first_seen_at),
                json.dumps(raw.payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        raw_id = int(cursor.lastrowid)
        if raw_id <= 0:
            await cursor.execute(
                "SELECT id FROM raw_items WHERE source_id=%s AND guid_hash=UNHEX(%s)",
                (raw.source_id, raw.guid_hash),
            )
            row = await cursor.fetchone()
            if row is None:
                raise StoreUnavailable("unable to resolve raw_items id after upsert")
            raw_id = int(row[0])
        return raw_id

    async def _upsert_event(self, cursor: Any, record: ObservationRecord) -> int:
        event = record.event
        await cursor.execute(
            """
            INSERT INTO events
                (event_fingerprint, canonical_url, canonical_title, institution, event_type,
                 published_at, first_seen_at, first_source_id, tags_json, rank_gold, rank_fx,
                 first_emitted_at)
            VALUES (UNHEX(%s), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) AS newrow
            ON DUPLICATE KEY UPDATE
                id = LAST_INSERT_ID(id),
                first_seen_at = LEAST(events.first_seen_at, newrow.first_seen_at),
                rank_gold = COALESCE(LEAST(events.rank_gold, newrow.rank_gold), events.rank_gold, newrow.rank_gold),
                rank_fx = COALESCE(LEAST(events.rank_fx, newrow.rank_fx), events.rank_fx, newrow.rank_fx),
                first_emitted_at = COALESCE(events.first_emitted_at, newrow.first_emitted_at)
            """,
            (
                event.event_fingerprint,
                event.canonical_url,
                event.canonical_title,
                event.institution,
                event.event_type,
                _mysql_dt(event.published_at),
                _mysql_dt(event.first_seen_at),
                event.first_source_id,
                json.dumps(event.tags, ensure_ascii=False),
                event.rank_gold,
                event.rank_fx,
                _mysql_dt(event.first_seen_at) if record.emitted else None,
            ),
        )
        event_id = int(cursor.lastrowid)
        if event_id <= 0:
            await cursor.execute("SELECT id FROM events WHERE event_fingerprint=UNHEX(%s)", (event.event_fingerprint,))
            row = await cursor.fetchone()
            if row is None:
                raise StoreUnavailable("unable to resolve events id after upsert")
            event_id = int(row[0])
        return event_id

    async def upsert_feed_state(self, state: SourceState) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await _ping(conn)
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO feed_state
                            (source_id, etag, last_modified, last_success_at, last_attempt_at,
                             consecutive_errors, last_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s) AS newrow
                        ON DUPLICATE KEY UPDATE
                            etag=newrow.etag, last_modified=newrow.last_modified,
                            last_success_at=newrow.last_success_at, last_attempt_at=newrow.last_attempt_at,
                            consecutive_errors=newrow.consecutive_errors, last_status=newrow.last_status
                        """,
                        (
                            state.source_id,
                            state.etag,
                            state.last_modified,
                            _mysql_dt(state.last_success_at),
                            _mysql_dt(state.last_attempt_at),
                            state.consecutive_errors,
                            state.last_status,
                        ),
                    )
                    await conn.commit()
            except Exception as exc:
                await conn.rollback()
                raise StoreUnavailable(f"feed_state update failed: {exc}") from exc

    async def recent_event_fingerprints(self, hours: int = 72) -> list[str]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await _ping(conn)
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT LOWER(HEX(event_fingerprint)) FROM events WHERE first_seen_at >= UTC_TIMESTAMP(6) - INTERVAL %s HOUR",
                    (hours,),
                )
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def recent_alert_fingerprints(self, hours: int = 72) -> list[str]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await _ping(conn)
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT LOWER(HEX(event_fingerprint)) FROM events "
                    "WHERE first_emitted_at IS NOT NULL AND first_seen_at >= UTC_TIMESTAMP(6) - INTERVAL %s HOUR",
                    (hours,),
                )
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]


async def _ping(conn: Any) -> None:
    try:
        await conn.ping(reconnect=True)
    except TypeError:
        await conn.ping()


def _mysql_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(tzinfo=None)
