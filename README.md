# MacroRSS

MacroRSS is a **low-latency, resilient macro-event sensor for Gold (XAUUSD) and Forex**.
It monitors first-hand official channels, normalizes documents into economic events, emits
high-impact events on a non-blocking hot path, then durably spools and persists observations.

The system is deliberately **not RSS-only**. Source adapters support RSS/Atom, official HTML
listings and JSON APIs without changing the scheduler/store core.

## Architecture

```text
official sources
      |
      v
async HTTP + conditional GET
      |
      v
parse -> normalize -> deterministic dedup
      |
      +----> HOT PATH: stdout / JSONL / ZeroMQ / webhook / Telegram
      |
      v
segmented local spool (append + fsync + atomic rename)
      |
      v
MySQL / InnoDB historical store
```

MySQL is **not** in the alert critical path. If MySQL or the LAN fails, collection and hot-path
emission continue; ready spool segments are replayed idempotently after recovery.

## Current source catalog

`config/feeds.yaml` currently contains 24 sources: 18 enabled and 6 retained but disabled until
a robust official machine-readable adapter is validated. High-priority channels include:

- Federal Reserve monetary-policy and all-press RSS;
- BLS latest releases;
- BEA news;
- **direct U.S. Treasury press-release HTML monitoring** plus Federal Register;
- ECB MID + press releases;
- BoJ, BoE, SNB, BoC and BIS;
- CFTC and SEC.

`config/events.yaml` contains current high-impact burst-polling windows for CPI, NFP, PPI,
JOLTS, PCE/GDP, FOMC and ECB decisions.

## Requirements

- Python >= 3.11
- Ubuntu/systemd recommended for production
- MySQL 8+ for central persistence (optional while testing; spool-only mode works without it)
- chrony/NTP synchronized host clock

## Development install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Database bootstrap

Run `deploy/schema.sql` as a MySQL administrator, then create a dedicated `macrorss` user with
only `SELECT, INSERT, UPDATE` on the `macrorss` database. See `deploy/grants.sql.example`.

Copy `.env.example` outside the repository, set `MACRORSS_DB_PASSWORD`, and never commit it.

## CLI

```bash
macrorss check-config
macrorss check-db
macrorss sources
macrorss probe fed-monetary
macrorss run
macrorss status
macrorss spool-status
macrorss tail --tag gold
macrorss replay-spool
macrorss emit-test
```

## Low-latency outputs

stdout JSON and a local JSONL event journal are enabled by default. Optional outputs are set by
environment variables:

```bash
MACRORSS_ZMQ_BIND=tcp://0.0.0.0:5557
MACRORSS_WEBHOOK_URL=http://127.0.0.1:9000/macrorss
MACRORSS_TELEGRAM_BOT_TOKEN=...
MACRORSS_TELEGRAM_CHAT_ID=...
```

ZeroMQ/webhook payloads include `event_fingerprint`, which is the consumer idempotency key.
Telegram is intended for human supervision, not as the primary automated trading transport.

## Latency metrics

MacroRSS records network, parse, hot-path, spool, source-lag and MySQL-flush measurements.
The initial internal SLO is:

- hot path p50 < 100 ms;
- hot path p99 < 500 ms;
- spool p99 < 1 s.

The system distinguishes its own processing latency from source/polling publication lag.

## Production deployment

See `doc/operacion.md` and `deploy/macrorss.service`. The service is configured with
`Restart=always`, journald logging, a dedicated unprivileged user and filesystem hardening.

## Design

The full rationale, phases, gates and failure model are in [`PLAN.md`](PLAN.md).

## License

MIT.
