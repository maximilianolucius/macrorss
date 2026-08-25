# Plan de trabajo: Sistema robusto de recolección de noticias macro

## Objetivo

Recolectar noticias de las 17 fuentes habilitadas en `config/feeds.yaml` con **mínimo delay** y **máxima resiliencia** (reinicios, cortes de luz, caídas de internet), sobre Ubuntu.

---

## Decisiones de arquitectura (a validar antes de empezar)

| Decisión | Propuesta | Alternativa | Justificación |
|---|---|---|---|
| Almacenamiento | **SQLite con WAL** | PostgreSQL | Cero dependencias de red, transaccional ante cortes de luz (WAL + fsync), suficiente para ~20 feeds. Postgres solo si luego hay múltiples consumidores |
| Cola de procesamiento | **Sin cola externa**: fetcher escribe directo a SQLite con dedup idempotente | Redis/RabbitMQ | Menos piezas que se rompen ante un corte de luz. La propia DB actúa como cola |
| Polling | **GET condicional** (ETag + Last-Modified) con intervalos por feed | Intervalo fijo global | Los .gov soportan cache headers: baja latencia sin baneos |
| Ejecución | **Un solo proceso daemon** en Python con scheduler async (asyncio) | cron + script | cron pierde eventos si la máquina estaba apagada; el daemon recupera al arrancar |
| Servicio | **systemd** con `Restart=always` + arranque en boot | supervisor, docker | Nativo de Ubuntu, sin dependencias extra |
| Notificación de noticias nuevas | **Fase 2**: webhook/Telegram/stdout estructurado | — | Primero recolectar confiable, después notificar rápido |
| Reloj del sistema | **chrony/NTP** obligatorio | — | Los timestamps de los feeds son inútiles si el reloj local drift tras un corte de luz (RTC sin batería) |

---

## Fases

### Fase 0 — Fundaciones del repo (0.5 día)

- Estructura de paquete: `macrorss/config.py`, `fetcher.py`, `store.py`, `daemon.py`, `models.py`.
- Loader validado de `config/feeds.yaml` (schema check con pydantic o validación manual).
- Logging estructurado (JSON, niveles, rotación vía journald).
- Dependencias mínimas: `httpx` (async + HTTP/2), `feedparser`, `pyyaml`.
- **Criterio de aceptación:** `macrorss --check-config` valida los 23 feeds y reporta errores con mensajes claros.

### Fase 1 — MVP funcional: fetch + store (1-2 días)

- Fetcher async con:
  - GET condicional (ETag/If-Modified-Since) por feed.
  - User-Agent de navegador (crítico para BLS, ya verificado que da 403 sin él).
  - Intervalos configurables por feed (Fed/BLS: 30-60s en ventana de datos; CFTC/SEC: 5-15 min).
- Store SQLite:
  - Tabla `items` con dedup por `(feed_id, guid)` y fallback a hash de `(title, link, published)`.
  - Tabla `feed_state`: ETag, Last-Modified, último fetch exitoso, contador de errores consecutivos.
  - Inserts idempotentes (`INSERT OR IGNORE`) → re-procesar nunca duplica.
- Normalización de timestamps a UTC (feedparser entrega formatos inconsistentes).
- **Criterio de aceptación:** corriendo 24h, recolecta items de los 17 feeds sin duplicados y con delay medido < 90s para feeds prioritarios.

### Fase 2 — Resiliencia a fallos (1-2 días)

- **Cortes de internet:** detección de fallo de red vs. fallo de feed (distinguir timeout global de HTTP 500 puntual). Backoff exponencial con jitter por feed; al recuperarse la conexión, re-fetch inmediato de todo y recuperación de items perdidos (los RSS sirven histórico, así que no se pierde nada: se atrasa).
- **Cortes de luz / reinicios:** todo estado en SQLite con WAL + `PRAGMA synchronous=NORMAL`; ningún estado crítico solo en memoria. Al arrancar, el daemon reanuda desde `feed_state` sin reprocesar.
- **Feeds que se rompen:** circuit breaker por feed (tras N errores consecutivos, backoff largo + alerta, sin tumbar el daemon).
- **Criterio de aceptación (test de caos):**
  1. `kill -9` al daemon en medio de un fetch → al reiniciar, cero duplicados y cero pérdida.
  2. Cortar red 30 min → al restaurar, recupera todos los items publicados en el corte.
  3. Apagar la máquina 1 hora → al boot, el servicio arranca solo y recupera lo publicado.

### Fase 3 — Servicio systemd + operación (0.5-1 día)

- Unit file: `Restart=always`, `RestartSec=5`, arranque tras `network-online.target`, límites de memoria, usuario dedicado sin privilegios.
- Logs a journald con prioridades; logrotate si se escribe a archivo.
- Configuración de **chrony** para sincronización de reloj (documentar, es prerequisito del sistema).
- Comandos CLI de operación: `macrorss status` (último fetch por feed, errores), `macrorss tail --tag gold`.
- **Criterio de aceptación:** `systemctl enable --now macrorss` sobrevive a `sudo reboot` sin intervención.

### Fase 4 — Notificación con bajo delay (1 día, opcional pero recomendado)

- Dispatcher de items nuevos: al insertar un item con `rank_gold/fx <= 5`, disparar notificación inmediata (Telegram bot / webhook / desktop notification — a definir).
- Filtrado por tags y keywords (ej. "CPI", "FOMC", "rate decision") para no ahogarse en ruido.
- Persistencia de "ya notificado" en SQLite → un reinicio no re-notifica.

### Fase 5 — Monitoreo y alertas del propio sistema (0.5-1 día)

- Heartbeat externo (healthchecks.io o similar): si el daemon no reporta en X min → alerta (cubre cortes de luz/internet totales, donde el propio sistema no puede avisar).
- Métricas internas: lag por feed (published_at vs fetched_at), tasa de errores, items/día.
- Alerta si un feed prioritario no publica en tiempo inusual (¿feed roto o silencio real? — detectar cambio de URL como el que ocurrió con Treasury).

### Fase 6 — Endurecimiento y docs (0.5 día)

- Suite de tests: unitarios (parsing, dedup, normalización) + los 3 tests de caos de Fase 2 automatizados en CI o script.
- `doc/operacion.md`: cómo agregar un feed, recuperarse de DB corrupta (`sqlite3 .recover`), qué revisar si no llegan noticias.
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
4. **Reloj del sistema tras corte de luz**: si el RTC pierde hora y NTP tarda en sincronizar, los delays medidos serán falsos → chrony es prerequisito, no opcional.

**Estimación total: 5-7 días de trabajo.**
