# Plan de trabajo: MacroRSS — low-latency macro event collector

## Objetivo

Construir un sistema robusto de **detección de eventos macroeconómicos de alto impacto para XAUUSD y Forex**, usando las fuentes de primera mano definidas en `config/feeds.yaml`, con dos objetivos simultáneos:

1. **mínima latencia de detección** para eventos market-moving;
2. **cero pérdida y operación resiliente** ante reinicios, cortes de luz, fallos de Internet, caída de MySQL o rotura de una fuente.

MacroRSS no debe diseñarse como un simple lector RSS. RSS/Atom será uno de varios mecanismos de adquisición. El núcleo debe soportar fuentes RSS, Atom, HTML, JSON/API y otros endpoints oficiales sin cambiar la arquitectura.

---

## Principios de diseño

### 1. Detection-first

La persistencia no debe estar en el camino crítico de una alerta.

```text
HTTP response
     |
     v
   parser
     |
     v
normalize + fast dedup
     |
     +--------------------> HOT PATH: event callback / ZMQ / webhook
     |
     v
 durable local spool
     |
     v
    MySQL
```

El sistema debe poder emitir un evento nuevo aunque MySQL esté temporalmente caído.

### 2. Multi-source, no RSS-centric

La abstracción central será `Source`, no `RSSFeed`.

Cada fuente declarará como mínimo:

- `transport`: `rss`, `atom`, `html`, `json`;
- `parser`: parser genérico o específico de la institución;
- URL/endpoints;
- prioridad;
- tags/mercados relevantes;
- política de polling;
- reglas de identificación del evento.

Esto permite incorporar Treasury, CME, WGC, LBMA, MOF Japan u otras fuentes sin deformar el núcleo.

### 3. Hot path y durable path separados

El hot path existe para reaccionar rápido.

El durable path existe para garantizar replay, auditoría e histórico.

Ninguna operación MySQL, compresión, análisis pesado o notificación lenta debe bloquear el parser/fetcher.

### 4. Idempotencia end-to-end

Re-fetch, replay del spool, reinicio del daemon o aparición simultánea del mismo comunicado en dos canales no deben generar eventos duplicados.

### 5. Medir la latencia, no asumirla

Cada evento debe guardar timestamps suficientes para separar:

- latencia de publicación de la fuente;
- latencia de polling;
- latencia de red;
- latencia de parsing;
- latencia del hot path;
- latencia de persistencia.

---

## Decisiones de arquitectura

| Decisión | Propuesta | Alternativa | Justificación |
|---|---|---|---|
| Modelo de adquisición | **Source adapters multi-transport** | RSS-only | Treasury y otras fuentes críticas no tienen RSS suficiente; el sistema debe soportar HTML/JSON/API sin rehacer el core |
| Ejecución | **Un daemon asyncio** con tareas independientes | cron + scripts | Scheduler fino, conexiones persistentes, polling adaptativo y menor overhead |
| HTTP | **httpx async**, keep-alive y HTTP/2 cuando aplique | requests/aiohttp | Pool de conexiones, timeouts explícitos y buena integración async |
| Polling | **Adaptativo por fuente y por ventana de evento** | intervalo fijo | Minimiza delay en CPI/NFP/FOMC sin bombardear servidores 24/7 |
| Hot path | **Callback/event bus local no bloqueante** | esperar DB antes de emitir | MySQL no debe agregar latencia ni bloquear detección |
| Buffer durable | **Spool local segmentado append-only + fsync + rename atómico** | JSONL único | Replay y recuperación de power-loss más simples y verificables |
| Almacenamiento | **MySQL 172.16.0.41:3306**, InnoDB, utf8mb4 | SQLite/PostgreSQL | Infra existente, RTT LAN bajo, histórico centralizado |
| Cola externa | **No inicialmente** | Redis/RabbitMQ/Kafka | ~20-30 fuentes no justifican complejidad; hot path + spool cubren el caso |
| Dedup documental | `source_id + guid_hash` | URL cruda | Idempotencia dentro de una fuente |
| Dedup cross-source | `event_fingerprint` + canonicalización | sólo dedup por feed | Evita dos alertas para el mismo FOMC/press release observado en canales distintos |
| Servicio | **systemd**, `Restart=always` | Docker/supervisor | Nativo de Ubuntu y simple de operar |
| Reloj | **chrony/NTP obligatorio** | reloj local sin control | La medición de latencia depende de timestamps confiables |

---

## Modelo conceptual

### Source

Representa un canal oficial observable.

Ejemplos:

```yaml
- id: fed-monetary
  transport: rss
  parser: feed
  url: https://www.federalreserve.gov/feeds/press_monetary.xml

- id: treasury-press
  transport: html
  parser: treasury_press
  url: https://home.treasury.gov/news/press-releases
```

Una institución puede tener múltiples `Source` redundantes.

### RawItem

Captura exacta del documento observado:

- `source_id`
- `guid`
- `guid_hash`
- `url`
- `title`
- `raw_published_at`
- `first_seen_at`
- payload/raw metadata necesarios para auditoría

### NormalizedEvent

Representa el evento económico, no el canal que lo publicó:

- `event_id`
- `event_fingerprint`
- `canonical_url`
- `canonical_title`
- `institution`
- `event_type`
- `published_at`
- `first_seen_at`
- `first_source_id`
- `tags`
- `rank_gold`
- `rank_fx`
- referencias a todos los `RawItem` que lo observaron

Así, un mismo FOMC statement detectado en `fed-monetary` y `fed-press-all` produce dos observaciones pero **un solo evento**.

---

## Latency accounting

Registrar monotonic clock para mediciones internas y UTC wall clock para auditoría.

Timestamps mínimos:

- `request_started_mono`
- `response_received_mono`
- `parsed_mono`
- `event_emitted_mono`
- `spooled_mono`
- `persisted_mono`
- `first_seen_at_utc`
- `published_at_utc` cuando la fuente lo provea

Métricas derivadas:

```text
network_fetch_ms = response_received - request_started
parse_ms         = parsed - response_received
hot_path_ms      = event_emitted - response_received
spool_ms         = spooled - response_received
persist_ms       = persisted - response_received
source_lag       = first_seen_at_utc - published_at_utc
```

`source_lag` mezcla retraso de publicación y polling; por eso debe analizarse junto al calendario de requests.

### SLO inicial del pipeline propio

Para payloads pequeños y fuentes normales:

- `hot_path_ms p50 < 100 ms`
- `hot_path_ms p99 < 500 ms`
- `spool_ms p99 < 1 s`

No usar `<90 s` como métrica del pipeline interno. Decenas de segundos sólo son aceptables cuando provienen del intervalo de polling o del propio proveedor.

---

## Polling adaptativo

Cada `Source` tendrá una política base y podrá entrar en ventanas de alta prioridad.

Ejemplo para una publicación conocida a `T0`:

```text
fuera de ventana:       30-60 s
T0 - 5 min a T0 - 30 s: 5 s
T0 - 30 s a T0 + 2 min: 1 s
T0 + 2 min a T0 + 10 m: 5 s
luego:                  volver a base
```

Los valores deben ser configurables por fuente y respetar comportamiento/rate limits del servidor.

### Eventos programados iniciales

Integrar un calendario operativo mínimo para:

- CPI
- NFP / Employment Situation
- PPI
- JOLTS cuando corresponda
- GDP
- PCE / Core PCE
- FOMC rate decisions/statements
- principales decisiones ECB/BoE/BoJ/SNB

No hace falta un calendario económico completo en la primera fase: sólo las ventanas que justifican polling agresivo.

### Conditional GET

Usar siempre que el servidor lo soporte:

- `If-None-Match` / `ETag`
- `If-Modified-Since` / `Last-Modified`

Un `304 Not Modified` debe ser la ruta normal y barata del polling frecuente.

---

## Spool durable segmentado

No usar un único JSONL infinito.

Estructura propuesta:

```text
spool/
  000000000001.open
  000000000002.ready
  000000000003.ready
```

### Escritura

1. append de records al segmento `.open`;
2. flush de userspace buffers;
3. `fsync(fd)` según política de lote/latencia;
4. al cerrar segmento, `fsync` y `rename()` atómico `.open -> .ready`;
5. `fsync` del directorio cuando sea necesario para durabilidad estricta.

### Flush a MySQL

1. leer segmento `.ready`;
2. insertar en transacción idempotente;
3. `COMMIT`;
4. marcar/eliminar segmento sólo después del commit confirmado.

### Power loss

Al iniciar:

- validar el último `.open`;
- ignorar/truncar sólo el último record parcial si existe;
- replayar todos los `.ready`;
- nunca descartar un record válido por no saber si llegó previamente a MySQL: el store debe ser idempotente.

### Rotación

Segmentar por tamaño o tiempo, por ejemplo 1-10 MB o pocos minutos. El valor final se medirá; el volumen del proyecto es pequeño.

---

## MySQL

MySQL opera como histórico, estado durable central y fuente para análisis; no como requisito del hot path.

### Conexión

Variables de entorno solamente:

- `MACRORSS_DB_HOST`
- `MACRORSS_DB_PORT`
- `MACRORSS_DB_USER`
- `MACRORSS_DB_PASSWORD`
- `MACRORSS_DB_NAME`

Cero credenciales en git.

Usar pool async con comprobación/reconexión de conexiones stale; fijar sesión UTC.

### Timestamps

Usar `DATETIME(6)` UTC, no `TIMESTAMP`.

### Dedup documental

`guid_hash BINARY(32)` = SHA-256 de GUID/canonical URL/fallback estable.

Índice único mínimo:

```text
UNIQUE(source_id, guid_hash)
```

No indexar GUIDs/URLs largas directamente.

### Dedup de eventos

Mantener una tabla/relación separada para eventos normalizados.

El fingerprint inicial puede construirse a partir de:

- institución;
- canonical URL;
- título normalizado;
- timestamp aproximado;
- tipo de evento.

No utilizar fuzzy matching costoso en el hot path inicial. Primero reglas deterministas rápidas; enriquecimiento posterior puede unir casos ambiguos.

---

## Hot path

La primera implementación debe incluir un dispatcher local desde Fase 1, aunque todavía no exista Telegram.

Interfaz conceptual:

```python
async def on_new_event(event: NormalizedEvent) -> None:
    ...
```

La llamada no debe bloquear fetching ni parsing. Los consumidores lentos deben recibir mediante una cola local acotada o tareas desacopladas.

### Salidas previstas

En orden de prioridad:

1. stdout JSON estructurado para validación;
2. ZeroMQ local/LAN para integración rápida con trading systems;
3. webhook HTTP;
4. Telegram para supervisión humana.

Telegram no es adecuado como transporte principal de una estrategia automática.

---

## Fases

### Fase 0 — Fundaciones y contratos

Crear:

```text
macrorss/
  config.py
  models.py
  sources/
    base.py
    feed.py
  fetcher.py
  normalizer.py
  dedup.py
  dispatcher.py
  spool.py
  store.py
  scheduler.py
  daemon.py
```

Tareas:

- loader validado de `config/feeds.yaml`;
- extender schema para `transport`, `parser`, políticas de polling y prioridad;
- dataclasses/pydantic models para `Source`, `RawItem`, `NormalizedEvent`;
- logging JSON estructurado;
- dependencias mínimas: `httpx`, `feedparser`, `pyyaml`, `asyncmy` y validación elegida;
- `macrorss --check-config`;
- `macrorss --check-db`;
- `deploy/schema.sql`.

**Gate F0:** todos los sources configuran correctamente; DB schema verificable; ningún secreto versionado.

### Fase 1 — Vertical slice low-latency

Implementar primero sólo fuentes prioritarias:

- Fed monetary
- Fed all press
- BLS
- BEA
- ECB MID

Pipeline completo:

```text
fetch -> parse -> normalize -> fast dedup -> emit -> spool -> MySQL
```

Incluir desde el comienzo medición de todos los timestamps de latencia.

**Gate F1:**

- detección y persistencia funcional;
- reiniciar no duplica;
- Fed duplicado entre feeds produce un solo `NormalizedEvent`;
- `hot_path_ms p99 < 500 ms` en pruebas locales;
- MySQL desconectado no impide emitir y spoolar eventos.

### Fase 2 — Scheduler adaptativo

- políticas base por source;
- event windows;
- conditional GET;
- jitter fuera de ventanas críticas para evitar sincronización innecesaria;
- re-fetch inmediato tras recuperación de conectividad;
- configuración especial para BLS/servidores con restricciones.

**Gate F2:** reproducir una ventana simulada de CPI/FOMC y verificar transición automática `normal -> burst -> normal` sin duplicados ni runaway polling.

### Fase 3 — Expansión multi-source

Agregar el resto de feeds operativos y comenzar adapters no-RSS prioritarios.

Prioridad especial:

1. **Treasury press / debt / refunding / buybacks**: no aceptar Federal Register como sustituto completo;
2. Presidential Documents / Federal Register;
3. BoE, BoJ, SNB, BoC, BIS;
4. CFTC/SEC;
5. después CME/WGC/LBMA/MOF cuando haya método oficial robusto.

**Gate F3:** catálogo operativo con health status por source y cobertura explícita de canales que hoy están sin RSS.

### Fase 4 — Resiliencia y chaos testing

Casos obligatorios:

1. `kill -9` durante fetch;
2. `kill -9` durante escritura de spool;
3. corte de Internet 30 min;
4. reboot de la máquina;
5. caída/bloqueo de MySQL 30 min;
6. último record del segmento parcialmente escrito;
7. replay deliberado dos veces del mismo spool;
8. dos sources publican el mismo evento con segundos de diferencia.

**Gate F4:** cero pérdida de records confirmados y cero alertas duplicadas para eventos identificados determinísticamente.

### Fase 5 — Operación systemd

- usuario dedicado sin privilegios;
- `Restart=always`;
- `RestartSec=5`;
- `After=network-online.target`;
- límites razonables de memoria/files;
- chrony documentado como prerequisito;
- journald;
- CLI:
  - `macrorss status`
  - `macrorss sources`
  - `macrorss tail --tag gold`
  - `macrorss spool-status`

**Gate F5:** reboot completo y recuperación automática sin intervención.

### Fase 6 — Output trading / notifications

- ZeroMQ publisher para integración automática;
- webhook;
- Telegram opcional para humano;
- filtros por mercado, ranking y event type;
- persistir estado de delivery cuando corresponda;
- consumidores idempotentes.

**Gate F6:** evento de prueba llega a consumidor automático sin esperar persistencia MySQL.

### Fase 7 — Observabilidad y source intelligence

Métricas:

- requests/source/min;
- HTTP status distribution;
- `304` ratio;
- fetch latency;
- parsing latency;
- hot-path latency;
- source lag;
- items/source/day;
- consecutive errors;
- spool bytes/age;
- MySQL flush lag;
- cross-source detection race: qué canal vio primero cada evento.

Esta última métrica es estratégica: después de varias semanas sabremos empíricamente si RSS, HTML o determinado endpoint gana para Fed/Treasury/ECB.

Alertas:

- daemon muerto;
- source prioritario con errores;
- source silencioso anormalmente;
- spool demasiado grande/viejo;
- MySQL unreachable;
- reloj/NTP fuera de tolerancia.

### Fase 8 — Hardening y documentación

- unit tests de parsers/normalización/fingerprints;
- fixtures reales sanitizados de fuentes;
- integration tests;
- chaos suite reproducible;
- `doc/operacion.md`;
- documentación de agregar Source/adapter;
- backup/restore MySQL;
- purga/replay manual del spool;
- arquitectura en `AGENTS.md`.

---

## Orden de implementación

```text
F0 -> F1 -> F2 -> F3 -> F4 -> F5 -> [F6 || F7] -> F8
```

La primera meta no es soportar 23 fuentes. La primera meta es demostrar un **vertical slice extremadamente confiable y rápido** con Fed/BLS/BEA/ECB; después escalar el catálogo.

---

## Riesgos principales

1. **Source publication lag**: MacroRSS no puede detectar un comunicado antes de que el endpoint observado lo publique. Por eso se deben comparar múltiples canales oficiales y medir quién gana.
2. **Rate limiting / anti-bot**: polling agresivo puede producir 403/429 o bloqueo. Burst polling sólo alrededor de releases conocidos y condicionado por comportamiento real de cada servidor.
3. **Treasury incompleto vía Federal Register**: Federal Register cubre regulatory/OFAC pero no sustituye necesariamente press releases, auctions, quarterly refunding o buybacks. Requiere adapter directo.
4. **RSS histórico limitado**: outages largos pueden superar la retención. Fuentes HTML/API redundantes ayudan pero no eliminan completamente el riesgo.
5. **MySQL `.41` es SPOF del histórico central**: mitigado para captura mediante spool, pero no para consultas históricas durante la caída.
6. **Durabilidad MySQL no totalmente controlada**: verificar `innodb_flush_log_at_trx_commit`; el spool local es la garantía primaria de captura.
7. **Cross-source dedup ambiguo**: fingerprints demasiado agresivos pueden fusionar documentos distintos; demasiado conservadores pueden duplicar alertas. Empezar determinista y auditable.
8. **Clock correctness**: NTP/chrony y monotonic clock son obligatorios para interpretar métricas de latencia.
9. **Hot-path backpressure**: un consumidor lento no puede bloquear el collector; las colas deben ser acotadas y observables.
10. **HTML adapters frágiles**: cualquier scraper debe tener fixtures, tests y alertas de cambio estructural.

---

## Criterio de éxito del proyecto

MacroRSS se considera exitoso cuando puede demostrar, con datos medidos y no sólo por diseño, que:

1. detecta eventos prioritarios de fuentes oficiales con una latencia dominada por el source/polling y no por procesamiento interno;
2. su hot path agrega menos de 500 ms p99 en condiciones normales;
3. continúa capturando durante caída de MySQL;
4. sobrevive a reboot/power-loss sin perder records confirmados;
5. no genera alertas duplicadas cuando el mismo evento aparece en varios canales conocidos;
6. permite determinar empíricamente qué source/channel detecta primero cada clase de evento;
7. puede incorporar una fuente HTML/JSON nueva sin modificar el núcleo del scheduler/store.

El objetivo final no es "leer RSS rápido". Es construir un **macro event sensor auditable, resiliente y de baja latencia para Gold y FX**.
