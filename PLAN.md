# Plan de trabajo: Sistema robusto de recolección de noticias macro

## Objetivo

Recolectar noticias de las 17 fuentes habilitadas en `config/feeds.yaml` con **mínimo delay** y **máxima resiliencia** (reinicios, cortes de luz, caídas de internet), sobre Ubuntu.

---

## Decisiones de arquitectura (a validar antes de empezar)

| Decisión | Propuesta | Alternativa | Justificación |
|---|---|---|---|
| Almacenamiento | **MySQL en 172.16.0.41:3306** (InnoDB, utf8mb4) | SQLite local, PostgreSQL | Instalación ya existente y en LAN (RTT medido 0.18 ms). Base de datos propia `macrorss`, usuario dedicado con grants acotados — no reutilizar bases ajenas del servidor |
| Buffer local | **Spool append-only JSONL en disco local**, flush a MySQL con reintento | Escribir directo a MySQL | **Obligatorio**: el store dejó de ser local, así que si .41 o la LAN caen el daemon perdería lo ya descargado. El spool absorbe la caída; `fsync` por lote da durabilidad ante corte de luz. No se usa SQLite como buffer por decisión explícita |
| Cola de procesamiento | **Sin cola externa**: spool local → MySQL con dedup idempotente | Redis/RabbitMQ | Menos piezas que se rompen. El par (spool, tabla `items`) actúa como cola |
| Polling | **GET condicional** (ETag + Last-Modified) con intervalos por feed | Intervalo fijo global | Los .gov soportan cache headers: baja latencia sin baneos |
| Ejecución | **Un solo proceso daemon** en Python con scheduler async (asyncio) | cron + script | cron pierde eventos si la máquina estaba apagada; el daemon recupera al arrancar |
| Servicio | **systemd** con `Restart=always` + arranque en boot | supervisor, docker | Nativo de Ubuntu, sin dependencias extra |
| Notificación de noticias nuevas | **Fase 2**: webhook/Telegram/stdout estructurado | — | Primero recolectar confiable, después notificar rápido |
| Reloj del sistema | **chrony/NTP** obligatorio | — | Los timestamps de los feeds son inútiles si el reloj local drift tras un corte de luz (RTC sin batería) |

---

## Fases

### Fase 0 — Fundaciones del repo (0.5 día)

- Estructura de paquete: `macrorss/config.py`, `fetcher.py`, `store.py`, `spool.py`, `daemon.py`, `models.py`.
- Loader validado de `config/feeds.yaml` (schema check con pydantic o validación manual).
- Logging estructurado (JSON, niveles, rotación vía journald).
- Dependencias mínimas: `httpx` (async + HTTP/2), `feedparser`, `pyyaml`, `asyncmy` (driver MySQL async; alternativa `aiomysql`).
- **Conexión a MySQL solo por variables de entorno** (`MACRORSS_DB_HOST/PORT/USER/PASSWORD/NAME`), leídas de `.env` fuera de git. El repo es público: cero credenciales versionadas.
- Migración inicial `deploy/schema.sql`: `CREATE DATABASE macrorss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` + usuario dedicado con `SELECT,INSERT,UPDATE` acotado a esa base.
- **Criterio de aceptación:** `macrorss --check-config` valida los 23 feeds del catálogo y reporta errores con mensajes claros; `macrorss --check-db` conecta a .41, verifica el schema y falla con mensaje accionable si no hay credenciales.

### Fase 1 — MVP funcional: fetch + store (1-2 días)

- Fetcher async con:
  - GET condicional (ETag/If-Modified-Since) por feed.
  - User-Agent de navegador (crítico para BLS, ya verificado que da 403 sin él).
  - Intervalos configurables por feed (Fed/BLS: 30-60s en ventana de datos; CFTC/SEC: 5-15 min).
- Spool local append-only (JSONL + `fsync` por lote): el fetcher escribe ahí primero y recién después flushea a MySQL. Un item confirmado en spool no se pierde aunque .41 esté caído.
- Store MySQL (InnoDB, `utf8mb4`):
  - Tabla `items` con dedup por índice único `(feed_id, guid_hash)`, donde `guid_hash` es `BINARY(32)` = SHA-256 del guid — **no indexar el guid crudo**: son URLs largas y InnoDB limita la clave a 3072 bytes. Fallback a hash de `(title, link, published)` cuando el feed no trae guid.
  - Tabla `feed_state`: ETag, Last-Modified, último fetch exitoso, contador de errores consecutivos.
  - Inserts idempotentes con `INSERT ... ON DUPLICATE KEY UPDATE` (no existe `INSERT OR IGNORE` en MySQL; `INSERT IGNORE` sirve pero silencia también otros errores) → re-procesar nunca duplica.
  - Timestamps en `DATETIME(6)` UTC, **no `TIMESTAMP`** (límite 2038 y conversión implícita de zona). Sesión fijada con `time_zone='+00:00'`.
  - Pool de conexiones con *pre-ping*: el `wait_timeout` del servidor mata conexiones ociosas y el daemon pasa horas sin escribir en feeds lentos.
- Normalización de timestamps a UTC (feedparser entrega formatos inconsistentes).
- **Criterio de aceptación:** corriendo 24h, recolecta items de los feeds operativos sin duplicados y con delay medido < 90s para feeds prioritarios.

### Fase 2 — Resiliencia a fallos (1-2 días)

- **Cortes de internet:** detección de fallo de red vs. fallo de feed (distinguir timeout global de HTTP 500 puntual). Backoff exponencial con jitter por feed; al recuperarse la conexión, re-fetch inmediato de todo y recuperación de items perdidos (los RSS sirven histórico, así que no se pierde nada: se atrasa).
- **Cortes de luz / reinicios:** ningún estado crítico solo en memoria. El spool local se escribe con `fsync` por lote (sobrevive al corte); en MySQL la durabilidad depende de `innodb_flush_log_at_trx_commit=1` — **verificar su valor en .41, es un servidor compartido y puede no estar bajo nuestro control**. Al arrancar, el daemon replaya el spool pendiente y reanuda desde `feed_state` sin reprocesar.
- **Feeds que se rompen:** circuit breaker por feed (tras N errores consecutivos, backoff largo + alerta, sin tumbar el daemon).
- **Caída de .41 o de la LAN:** el fetcher NO se detiene — sigue descargando y acumulando en el spool; un flusher independiente reintenta con backoff. Alerta si el spool supera un umbral de tamaño o antigüedad.
- **Criterio de aceptación (test de caos):**
  1. `kill -9` al daemon en medio de un fetch → al reiniciar, cero duplicados y cero pérdida.
  2. Cortar red 30 min → al restaurar, recupera todos los items publicados en el corte.
  3. Apagar la máquina 1 hora → al boot, el servicio arranca solo y recupera lo publicado.
  4. **Detener MySQL en .41 durante 30 min** (o bloquear 3306 con firewall) → el fetcher sigue trabajando, el spool crece, y al restaurar se vuelca todo sin duplicados ni pérdida.

### Fase 3 — Servicio systemd + operación (0.5-1 día)

- Unit file: `Restart=always`, `RestartSec=5`, arranque tras `network-online.target`, límites de memoria, usuario dedicado sin privilegios.
- Logs a journald con prioridades; logrotate si se escribe a archivo.
- Configuración de **chrony** para sincronización de reloj (documentar, es prerequisito del sistema).
- Comandos CLI de operación: `macrorss status` (último fetch por feed, errores), `macrorss tail --tag gold`.
- **Criterio de aceptación:** `systemctl enable --now macrorss` sobrevive a `sudo reboot` sin intervención.

### Fase 4 — Notificación con bajo delay (1 día, opcional pero recomendado)

- Dispatcher de items nuevos: al insertar un item con `rank_gold/fx <= 5`, disparar notificación inmediata (Telegram bot / webhook / desktop notification — a definir).
- Filtrado por tags y keywords (ej. "CPI", "FOMC", "rate decision") para no ahogarse en ruido.
- Persistencia de "ya notificado" como columna/tabla en MySQL → un reinicio no re-notifica. Marcar con `UPDATE ... WHERE notified_at IS NULL` para que sea idempotente ante dos instancias.

### Fase 5 — Monitoreo y alertas del propio sistema (0.5-1 día)

- Heartbeat externo (healthchecks.io o similar): si el daemon no reporta en X min → alerta (cubre cortes de luz/internet totales, donde el propio sistema no puede avisar).
- Métricas internas: lag por feed (published_at vs fetched_at), tasa de errores, items/día.
- Alerta si un feed prioritario no publica en tiempo inusual (¿feed roto o silencio real? — detectar cambio de URL como el que ocurrió con Treasury).

### Fase 6 — Endurecimiento y docs (0.5 día)

- Suite de tests: unitarios (parsing, dedup, normalización) + los 3 tests de caos de Fase 2 automatizados en CI o script.
- `doc/operacion.md`: cómo agregar un feed, cómo purgar/replayar el spool a mano, backup y restore de la base MySQL (`mysqldump --single-transaction`), qué revisar si no llegan noticias.
- Actualizar `AGENTS.md` con arquitectura y convenciones.

---

## Orden y dependencias

```
Fase 0 → Fase 1 → Fase 2 → Fase 3 → [Fase 4 ∥ Fase 5] → Fase 6
```

Fases 4 y 5 son independientes entre sí y pueden paralelizarse u omitirse temporalmente (el sistema ya es útil al cierre de Fase 3).

## Riesgos principales identificados de antemano

1. **BLS y sitios .gov con anti-bot**: mitigado con UA de navegador (verificado), pero puede escalar a bloqueo por IP si el polling es agresivo → intervalos mínimos razonables (30-60s, no 5s).
2. **RSS sirve histórico limitado**: si la máquina está apagada más tiempo del que el feed retiene items (típicamente 10-50 items), esos items se pierden para siempre. Es un límite inherente de RSS; la mitigación es el heartbeat externo para enterarse rápido del corte.
3. **Feeds que cambian de URL sin aviso** (caso Treasury): el circuit breaker + alerta de "feed silencioso" de Fase 5 lo detecta, pero la corrección es manual.
4. **El store dejó de ser local (.41 es un punto único de fallo nuevo)**: si el servidor se cae, se llena el disco o alguien reinicia MySQL, el daemon ya no puede persistir. Mitigado con el spool local + flusher con reintento, pero el spool tiene un techo de disco: hay que alertar antes de llenarlo. Es un servidor **compartido**, así que su carga y sus reinicios no los controlamos nosotros.
5. **Durabilidad no controlada por nosotros**: `innodb_flush_log_at_trx_commit` en .41 puede estar en 0 o 2 (más rápido, pierde hasta 1s de transacciones ante crash). Verificarlo; si no se puede cambiar, el spool local es la única garantía real.
6. **Reloj del sistema tras corte de luz**: si el RTC pierde hora y NTP tarda en sincronizar, los delays medidos serán falsos → chrony es prerequisito, no opcional.

**Estimación total: 6-8 días de trabajo** (+0.5-1 día vs. el plan con SQLite: schema/migración MySQL, spool local y el test de caos de caída de .41).
