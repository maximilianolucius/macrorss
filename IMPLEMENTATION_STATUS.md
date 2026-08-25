# MacroRSS implementation status

This file separates **implemented code**, **validated live behavior**, and **host-local operational
state**. The repository can prove code, tests and recorded smoke validations; whether a daemon is
running at this instant is authoritative only on the deployment host (`systemctl` + runtime metrics).

## F0 — Foundations and contracts: IMPLEMENTED + CI VALIDATED

- validated source/config loader;
- explicit multi-transport source schema;
- core dataclasses and JSON logging;
- MySQL schema and env-only credentials;
- `check-config` / `check-db`;
- strict mypy is enforced in CI.

## F1 — Low-latency vertical slice: IMPLEMENTED + VALIDATED

- async HTTP keep-alive/HTTP2;
- RSS/Atom parsing;
- normalization and document/event identity;
- bounded non-blocking dispatcher;
- segmented durable spool;
- async MySQL flusher;
- restart-safe recent dedup seed;
- latency metrics.

CI exercises MySQL 8 schema/upsert/replay idempotence. Live DB testing also exercised the spool
failure boundary: a deliberately broken SQL upsert caused every DB flush to fail while records
remained retained for replay rather than being lost.

## F2 — Adaptive scheduler: IMPLEMENTED

- source-specific base policy;
- pre/burst/post windows;
- high-impact UTC event calendar;
- conditional GET;
- jitter outside burst;
- exponential per-source backoff and circuit breaker.

## F3 — Multi-source expansion: IMPLEMENTED FOR VALIDATED CHANNELS

24 sources are catalogued and 18 are enabled. Live endpoint debugging found and fixed three
important silent-failure modes:

- BLS dashboard releases now use content-aware document identity instead of a constant link;
- Treasury direct HTML parsing excludes navigation links and captures release slugs;
- Federal Register sources use the documented JSON API instead of RSS endpoints redirected to an
  anti-bot wall.

Six catalog entries remain deliberately disabled until a robust official adapter is validated.

## F4 — Resilience / chaos: AUTOMATED COVERAGE IMPLEMENTED

Automated tests cover torn final spool records, replay readability, idempotent persistence and
cross-source deterministic dedup. `scripts/chaos-checklist.sh` defines destructive host/network/
MySQL tests.

Destructive power/network/reboot drills are host-level operational validation and should not be
represented as complete unless their results are explicitly recorded.

## F5 — systemd operations: IMPLEMENTED

- hardened system service and install helper;
- documented `systemd --user` alternative;
- status/sources/tail/spool/replay CLI;
- journald logging;
- chrony/NTP prerequisite.

Use `systemctl status macrorss` or `systemctl --user status macrorss` on the target host for current
service liveness; GitHub cannot establish that runtime fact by itself.

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

Long-horizon silent-source thresholds remain source-specific and should be calibrated from observed
history rather than guessed globally.

## F8 — Hardening/docs: IMPLEMENTED

- unit/regression fixtures;
- MySQL integration CI;
- strict mypy CI gate;
- operations and architecture docs;
- contributor invariants;
- chaos checklist;
- schema/replay instructions.

## Recorded validation

### Live environment

Recorded in merged production-debug changes:

- real backend: MySQL 8.0.42 at `172.16.0.41`, reached through ProxySQL `6033`;
- 45-second daemon smoke run: 341 raw items ingested from 18/18 enabled sources with zero errors;
- after the MySQL upsert fix: zero deprecation warnings, zero errors and zero deferred flushes;
- idempotent re-run left counts unchanged at 341 `raw_items`, 332 `events`, 18 `feed_state` rows;
- live source checks confirmed BLS content dedup, Treasury release filtering and Federal Register
  JSON API behavior.

### GitHub CI (`main`)

Latest recorded gate:

- schema application against MySQL 8.4: PASS;
- `ruff check .`: PASS;
- `mypy macrorss`: PASS (24 source files);
- `python -m compileall -q macrorss tests`: PASS;
- `pytest --cov=macrorss --cov-report=term-missing`: **30 PASS**, 56% aggregate coverage;
- `macrorss check-config`: PASS (24 sources, 18 enabled; RSS 16 / HTML 6 / JSON 2; 24 scheduled events);
- `macrorss check-db`: PASS.

The remaining operational distinction is intentional: repository validation and live smoke tests are
recorded here, while the **current** running/stopped state of a deployed service belongs to the host.
