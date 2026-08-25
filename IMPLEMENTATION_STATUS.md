# MacroRSS implementation status

This file separates **implemented code** from **environmental validation that must run on the
production host/LAN**.

## F0 — Foundations and contracts: IMPLEMENTED

- validated source/config loader;
- explicit multi-transport source schema;
- core dataclasses;
- JSON logging;
- MySQL schema and env-only credentials;
- `check-config` / `check-db`.

## F1 — Low-latency vertical slice: IMPLEMENTED

- async HTTP keep-alive/HTTP2;
- RSS/Atom parsing;
- normalization and document/event identity;
- bounded non-blocking dispatcher;
- segmented durable spool;
- async MySQL flusher;
- restart-safe recent dedup seed;
- latency metrics.

Local unit suite validates the pipeline components. CI includes a real MySQL 8 service test for
schema/upsert/replay idempotence.

## F2 — Adaptive scheduler: IMPLEMENTED

- source-specific base policy;
- pre/burst/post windows;
- current high-impact UTC event calendar;
- conditional GET;
- jitter outside burst;
- exponential per-source backoff and circuit breaker.

## F3 — Multi-source expansion: IMPLEMENTED FOR VALIDATED CHANNELS

18 sources are enabled. Treasury direct HTML monitoring is implemented in addition to Federal
Register. Six catalog entries remain deliberately disabled until a robust official adapter is
validated; enabling an unverified scraper would violate the source-quality gate.

## F4 — Resilience / chaos: CODE + AUTOMATED FIXTURES IMPLEMENTED

Automated tests cover torn final spool records, replay readability and cross-source deterministic
dedup. `scripts/chaos-checklist.sh` defines destructive host/network/MySQL tests.

**Production-host destructive chaos execution remains environmental validation** because it
requires control of the target Ubuntu host, its network and MySQL service.

## F5 — systemd operations: IMPLEMENTED

- hardened unit;
- install helper;
- status/sources/tail/spool/replay CLI;
- journald logging;
- chrony/NTP documented prerequisite.

Actual reboot validation must run on the deployment host.

## F6 — Trading outputs: IMPLEMENTED

- stdout JSON;
- local JSONL event journal;
- ZeroMQ PUB;
- webhook;
- Telegram optional;
- deterministic `event_fingerprint` carried to consumers.

`macrorss emit-test` validates configured sinks without requiring MySQL.

## F7 — Observability/source intelligence: IMPLEMENTED CORE

- HTTP/status counters;
- network/parse/hot-path/spool/MySQL latency;
- source lag;
- source error state;
- spool size/age;
- dispatcher depth;
- cross-source race counters;
- optional external heartbeat.

Long-horizon "silent source" thresholds are intentionally not hard-coded globally because normal
publication cadence differs substantially by institution; this should be calibrated from observed
history rather than guessed.

## F8 — Hardening/docs: IMPLEMENTED

- unit fixtures/tests;
- MySQL integration CI;
- operations and architecture docs;
- contributor invariants;
- chaos checklist;
- schema/replay instructions.

## Validation executed in the implementation environment

- `pytest`: PASS (25 tests + MySQL integration test skipped locally when no MySQL service exists);
- `python -m compileall -q macrorss tests`: PASS;
- `python -m macrorss check-config`: PASS (24 sources, 18 enabled, 24 scheduled events).

GitHub CI is the authoritative environment for `ruff` and the real MySQL 8 integration test.
