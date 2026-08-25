# MacroRSS architecture

## Hot path vs durable path

The hot path ends when a normalized high-impact event is successfully enqueued to the local
bounded dispatcher. Remote sinks run in a worker and cannot delay fetch/parse. The durable path
then writes the observation to the local spool and asynchronously flushes to MySQL.

## Cross-source model

A source produces `RawItem` observations. `normalize_event()` maps them to `NormalizedEvent`.
`event_fingerprint` intentionally excludes `source_id`, allowing two official channels for the same
document (for example Fed monetary and Fed all-press) to resolve to one alert while preserving both
raw observations in MySQL.

## Startup bootstrap

On a source's first successful poll after a clean installation, existing listing/feed history is
spooled but not alerted (`MACRORSS_EMIT_BOOTSTRAP=0`). This prevents a daemon first-start from
firing dozens of stale headlines. Subsequent newly observed documents are eligible normally.

## Source-race intelligence

Cross-source duplicates increment race counters. Over time these measurements show empirically
which official channel tends to expose each event first; source rankings can then be based on data
rather than assumptions.
