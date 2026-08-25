# MacroRSS architecture and contributor contract

## Non-negotiable invariants

1. **Detection first.** Never put MySQL, Telegram, webhook latency, expensive NLP or other remote
   dependencies before the hot-path enqueue.
2. **Durability after emission.** Every new observation must enter the local segmented spool even
   when MySQL is unavailable.
3. **Idempotence.** Re-fetch, restart, spool replay and cross-source duplicates must not create
   duplicate stored observations or duplicate alerts for a deterministic event fingerprint.
4. **Source abstraction.** Add source adapters through `SourceConfig.transport/parser`; do not add
   institution-specific branches to the scheduler/store core.
5. **Clock discipline.** UTC wall clock is for audit; monotonic clock is for internal latency.
6. **No secrets in git.** DB, webhook and Telegram credentials are environment-only.

## Pipeline

`fetcher -> source parser -> normalizer -> document/event dedup -> dispatcher -> spool -> store`

The dispatcher uses a bounded queue. A slow consumer must never block polling.

## Data identities

- document identity: `(source_id, guid_hash)`
- event identity: `event_fingerprint`
- delivery idempotency: `(event_fingerprint, sink)` conceptually

Keep raw observations even when multiple sources map to one normalized event; source-race data is
strategically valuable.

## Spool

`*.open` -> fsync -> atomic rename to `*.ready` -> MySQL transaction -> `archive/*.done`.
Archived segments are retained temporarily so restart dedup still works when MySQL is unavailable.
Only the final torn JSON record of a recovered `.open` segment may be truncated.

## Tests required for changes

At minimum run:

```bash
pytest
python -m compileall -q macrorss tests
python -m macrorss check-config
```

Parser changes need real-but-sanitized fixtures. Spool/store changes need idempotency/recovery tests.
Scheduler changes need normal/pre/burst/post transition tests.
