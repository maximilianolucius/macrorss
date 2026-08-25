# MacroRSS documentation

This directory contains the design and operating documentation for the implemented collector.

## Index

- [`architecture.md`](architecture.md) — component model, data flow and failure boundaries.
- [`operacion.md`](operacion.md) — deployment pre-flight, service operation, recovery and chaos checks.
- [`fuentes-primera-mano-gold-fx.md`](fuentes-primera-mano-gold-fx.md) — first-hand source catalog and XAUUSD/FX impact rationale.
- [`../PLAN.md`](../PLAN.md) — original phased design, acceptance gates and failure model.
- [`../IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md) — current implementation and validation status.

## Documentation invariants

- Treat `config/feeds.yaml` and `config/events.yaml` as the authoritative machine-readable source
  catalog and event calendar.
- Do not document credentials, tokens, private environment files or production secrets.
- Distinguish code/CI validation from live-host liveness. Git records what was built and tested;
  `systemctl`/runtime metrics are authoritative for whether a deployed daemon is currently running.
- When an official endpoint changes, update the source adapter, fixture/regression test and relevant
  documentation together.
