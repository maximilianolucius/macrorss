#!/usr/bin/env bash
set -euo pipefail

cat <<'CHECKLIST'
MacroRSS destructive chaos checklist (run on a test host/database):

[ ] Baseline: macrorss check-config && macrorss check-db
[ ] Start daemon; record spool-status and event count
[ ] kill -9 daemon during active fetch; restart; verify no duplicate alert
[ ] kill -9 repeatedly during spool writes; restart; verify only torn final line is discarded
[ ] Block outbound Internet for 30 minutes; restore; verify per-source recovery
[ ] Reboot host; verify systemd starts MacroRSS automatically
[ ] Block TCP/3306 to MySQL for 30 minutes; verify hot path continues and ready spool grows
[ ] Restore MySQL; verify ready spool drains to archive with no duplicate DB rows
[ ] Copy a ready segment and replay it twice against test DB; verify idempotence
[ ] Feed same official document through two source fixtures; verify one event alert, two observations
[ ] Confirm hot_path_ms p99 < 500 ms on local fixture benchmark
[ ] Confirm chrony/NTP reports synchronized time
CHECKLIST
