# MacroRSS

**Low-latency, resilient macro-event sensor for Gold (XAUUSD) and Forex.**

MacroRSS monitors first-hand official channels (central banks, statistical agencies,
regulators), normalizes each document into an economic event, emits high-impact events on a
non-blocking hot path, and then durably spools and persists every observation. It is
deliberately **not RSS-only**: source adapters handle RSS/Atom, official HTML listings and
JSON APIs behind one scheduler/store core.

> **Status:** implemented end-to-end and validated against the live MySQL backend
> (172.16.0.41 via ProxySQL). A 45 s daemon run ingested 341 items from 18/18 enabled
> sources with zero errors. What remains is production deployment and the destructive
> chaos drills — see [Roadmap](#roadmap).

## Architecture

```text
official sources (RSS/Atom · HTML · JSON API)
      │
      ▼
async HTTP + conditional GET (ETag / If-Modified-Since)
      │
      ▼
parse ─► normalize ─► deterministic document + event dedup
      │
      ├──► HOT PATH  (never blocked by the DB): stdout · JSONL · ZeroMQ · webhook · Telegram
      │
      ▼
segmented local spool  (append + fsync + atomic rename, torn-record recovery)
      │
      ▼
MySQL / InnoDB historical store  (idempotent replay)
```

**MySQL is not in the alert critical path.** If MySQL or the LAN fails, collection and
hot-path emission continue; ready spool segments replay idempotently after recovery. This is
the core resilience property, because the historical store lives on a shared server we do not
fully control (see [Durability](#durability)).

## Source catalog

`config/feeds.yaml` — 24 sources, 18 enabled, 6 retained-but-disabled until a robust official
machine-readable adapter is validated (enabling an unverified scraper would violate the
source-quality gate). High-priority channels:

| Market driver | Sources |
|---|---|
| US macro (moves USD, yields, XAUUSD) | Federal Reserve (monetary + all-press), BLS, BEA |
| US policy / sanctions | Treasury **direct press-release HTML** + Federal Register JSON API, Presidential Documents |
| Non-US central banks | ECB (MID + press), BoJ, BoE, SNB, BoC, BIS speeches |
| Regulation / positioning | CFTC (press + enforcement), SEC |

`config/events.yaml` — high-impact burst-polling windows (CPI, NFP, PPI, JOLTS, PCE/GDP,
FOMC, ECB decisions), so priority feeds poll tighter around scheduled releases.

Two source types need content-aware handling and are configured in the catalog:

- **Dashboard feeds** (e.g. BLS `bls_latest.rss`) ship a single item with a constant `<link>`;
  the numbers live in the body. They set `parser_options: {dedup: content}` so each release is
  detected — guid-only identity would drop every update after the first.
- **Anti-bot walls** (Federal Register `/documents/search?...&format=rss` 302s to an "unblock"
  page) are routed through the documented JSON API instead.

## Requirements

- Python ≥ 3.11
- MySQL 8+ for central persistence (optional while testing — spool-only mode works without it)
- Ubuntu / systemd recommended for production
- chrony/NTP-synchronized host clock (feed timestamps are meaningless if the clock drifts)

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest                 # unit + regression suite

cp .env.example .env   # then edit; .env is gitignored — never commit credentials
macrorss check-config  # validate feeds + event calendar
macrorss check-db      # connect to MySQL, validate schema + durability
macrorss probe fed-monetary   # fetch+parse one source once, no writes
macrorss run           # run the collector daemon
```

## Database bootstrap

The repository is **public**: credentials live only in `.env` (gitignored) and are read from
the environment (`MACRORSS_DB_*`). Nothing else is committed.

As a MySQL administrator, create the database and a dedicated application user:

```sql
CREATE DATABASE macrorss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'macrorss'@'%' IDENTIFIED BY '<strong-password>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER, REFERENCES
  ON macrorss.* TO 'macrorss'@'%';
FLUSH PRIVILEGES;
```

Then apply the schema (`deploy/schema.sql`) once and point `.env` at the server.

Notes from a real deployment:

- If the server enforces `validate_password` (policy MEDIUM), the app password needs
  upper+lower, a digit and a special character, length ≥ 8.
- Behind **ProxySQL**, the application connects on the ProxySQL port (e.g. `6033`), and the
  user must also be registered in ProxySQL's `mysql_users` (same hostgroup as your other
  app users) — creating it in the MySQL backend alone is not routable.
- `check-db` reports `innodb_flush_log_at_trx_commit`; if it is not `1`, the local spool is
  your primary crash guarantee (see below).

## CLI

```bash
macrorss check-config    # validate feeds + event calendar
macrorss check-db        # MySQL schema + durability check
macrorss sources         # list configured sources
macrorss probe <id>      # fetch + parse one source once (no writes)
macrorss run             # run the daemon
macrorss status          # last metrics/status snapshot
macrorss spool-status    # local durable spool status
macrorss replay-spool    # flush ready spool segments to MySQL now
macrorss tail --tag gold # recent locally emitted events
macrorss emit-test       # emit a synthetic event through configured sinks
```

## Low-latency outputs

stdout JSON and a local JSONL event journal are on by default. Optional sinks via environment:

```bash
MACRORSS_ZMQ_BIND=tcp://0.0.0.0:5557
MACRORSS_WEBHOOK_URL=http://127.0.0.1:9000/macrorss
MACRORSS_TELEGRAM_BOT_TOKEN=...
MACRORSS_TELEGRAM_CHAT_ID=...
```

ZeroMQ/webhook payloads carry `event_fingerprint`, the consumer's idempotency key. Telegram is
for human supervision, not the primary automated trading transport.

Internal SLO: hot path p50 < 100 ms, p99 < 500 ms; spool p99 < 1 s. The system separates its
own processing latency from source/polling publication lag.

## Deployment

Two options depending on the host:

- **Production host (`/opt`, hardened):** `deploy/install-systemd.sh` installs a dedicated
  unprivileged user, `/opt/macrorss`, `EnvironmentFile=/etc/macrorss/macrorss.env`, and a unit
  with `Restart=always`, journald logging and filesystem hardening. Requires root.
- **Workstation (`systemd --user`):** run as your own user from a checkout, with
  `loginctl enable-linger` so it starts at boot without a login session. No root required;
  fewer OS-level hardening guarantees than `/opt`.

See `doc/operacion.md` for operations (adding a feed, replaying the spool, backup/restore) and
`doc/architecture.md` for the component model.

## Durability

The historical store runs on a shared MySQL server that may set
`innodb_flush_log_at_trx_commit` to 0 or 2 (faster, but up to ~1 s of transactions lost on
crash) — outside our control. The **local append-only spool with per-batch fsync is therefore
the primary durability guarantee**: the fetcher never blocks on the DB, records survive a
process kill or power loss, and a flusher replays them idempotently once MySQL is reachable.

## Design

Full rationale, phases, acceptance gates and failure model: [`PLAN.md`](PLAN.md).
Per-phase implementation status: [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).

## License

MIT — see [`LICENSE`](LICENSE).
