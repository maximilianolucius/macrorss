# MacroRSS — operación y recuperación

## 1. Pre-flight

1. Host clock synchronized with chrony/NTP.
2. Python virtualenv installed with `pip install -e .`.
3. `config/feeds.yaml` and `config/events.yaml` validated with `macrorss check-config`.
4. MySQL schema installed from `deploy/schema.sql`.
5. Dedicated DB credentials loaded from `/etc/macrorss/macrorss.env` or another non-git env file.
6. `macrorss check-db` reports all required tables.

If `innodb_flush_log_at_trx_commit` is not `1`, MacroRSS still captures durably through its local
spool, but MySQL alone cannot be treated as the crash-loss boundary.

When ProxySQL is used, point `MACRORSS_DB_PORT` at the ProxySQL listener (validated deployment:
`6033`) and ensure the application user is configured both in backend MySQL and ProxySQL.

## 2. Start / stop

### Hardened system service

```bash
sudo systemctl enable --now macrorss
sudo systemctl status macrorss
journalctl -u macrorss -f
```

### User service

For a non-root/workstation deployment:

```bash
systemctl --user enable --now macrorss
systemctl --user status macrorss
journalctl --user -u macrorss -f
```

If it must start at boot without an interactive login:

```bash
loginctl enable-linger "$USER"
```

The live `systemctl ... status` output and MacroRSS runtime metrics are authoritative for whether a
deployed daemon is currently running; Git commit state alone is not a liveness check.

Graceful stop seals the current spool segment. `kill -9` is also recoverable: on next start the
last `.open` segment is truncated only to its last complete newline and converted to `.ready`.

## 3. Runtime inspection

```bash
macrorss status
macrorss sources
macrorss spool-status
macrorss tail --tag gold -n 20
```

Watch especially:

- `hot_path_ms` p99;
- `spool_ms` p99;
- consecutive source errors;
- `ready_bytes` / oldest ready-segment age;
- MySQL flush errors;
- cross-source race counters.

## 4. MySQL outage

No collector restart is required. Fetching, event emission and spool writes continue.

After MySQL returns, the background flusher automatically replays `*.ready`. Manual replay:

```bash
macrorss replay-spool
```

Replay is idempotent because raw documents and events have unique deterministic keys.

## 5. Internet outage

Source loops back off independently. On recovery they immediately resume polling; RSS/HTML source
history determines how much outage history can be recovered. Long outages can exceed provider
retention and are therefore externally monitored by the optional heartbeat.

## 6. Broken source / changed page

```bash
macrorss probe SOURCE_ID
```

- HTTP errors indicate transport/rate-limit/access issues.
- HTTP 200 with zero parsed items on a normally active source points to a parser/page change.
- Dashboard feeds whose URL/guid is stable across releases require content-aware deduplication.
- HTML adapters must be updated together with a fixture and parser test.
- Prefer an official documented JSON API when an RSS endpoint redirects to an anti-bot page.

Never silently replace a first-hand channel with a slower aggregator without documenting the
latency/capability trade-off.

## 7. Adding a source

Add an entry in `config/feeds.yaml` specifying `transport`, `parser`, ranking/tags and polling.

For RSS/Atom use `parser: feed`. For official JSON use `parser: generic_json` with `parser_options`.
For HTML, implement a narrow parser in `macrorss/sources/`, register it in `sources/base.py`, and add
a fixture/test. Do not put HTML-specific logic into `fetcher.py` or `scheduler.py`.

## 8. Event calendar

`config/events.yaml` uses explicit UTC times. Refresh it before its final listed event expires.
Burst windows are deliberately narrow so normal polling remains respectful of official sites.

## 9. Backups

Central history:

```bash
mysqldump --single-transaction --routines --triggers macrorss > macrorss.sql
```

The local spool is not a long-term backup. `archive/*.done` is a short rolling recovery/dedup cache.

## 10. Chaos checks before production changes

Run `scripts/chaos-checklist.sh` and perform destructive cases only on a test host/database.
The acceptance condition is zero loss of confirmed spool records and zero deterministic duplicate
alerts after replay/restart.
