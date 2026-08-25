# Fuentes de primera mano para Gold (XAUUSD) y Forex — ordenadas por impacto

> URLs verificadas con `curl` el 2026-08-25. Config lista para macrorss en `config/feeds.yaml`.

## ⚠️ Notas de verificación (testeadas en vivo)

- ✅ Fed: `https://www.federalreserve.gov/feeds/press_all.xml` y `press_monetary.xml` (FOMC específico) → 200
- ✅ BLS: `bls_latest.rss` existe pero devuelve **403 a bots** — el fetcher necesita `User-Agent` de navegador
- ✅ BEA: `https://www.bea.gov/news/rss` → 200
- ✅ ECB MID: `https://mid.ecb.europa.eu/rss/mid.xml` → 200
- ✅ BoE: `https://www.bankofengland.co.uk/rss/news` → 200
- ✅ BoJ: `https://www.boj.or.jp/en/rss/whatsnew.xml` → 200
- ✅ SNB: `https://www.snb.ch/public/rss/en/news` y `/public/rss/en/mopo` → 200
- ✅ SEC: `https://www.sec.gov/news/pressreleases.rss` → 200
- ✅ CFTC: feeds reales en `/RSS/RSSGP/rssgp.xml` (press) y `/RSS/RSSENF/rssenf.xml` (enforcement)
- ✅ BIS: `https://www.bis.org/doclist/cbspeeches.rss` (discursos de banqueros centrales)
- ❌ **Treasury ya NO tiene RSS** en su sitio (eliminado). Alternativa verificada: **Federal Register** con RSS por agencia, ej. `https://www.federalregister.gov/documents/search?conditions[agencies][]=treasury-department&format=rss` → 200

## Fuentes adicionales recomendadas (no estaban en la lista original)

1. **Federal Register** — no es opcional si se quiere primera mano: tarifas/aranceles, sanciones OFAC, órdenes ejecutivas. En 2024-2025 esto movió oro y USD más que muchos datos macro. RSS por agencia o por tipo de documento (`PRESDOCU`).
2. **BIS — Central bank speeches** (`cbspeeches.rss`) — un solo feed que agrega discursos de TODOS los banqueros centrales del mundo. Ahorra suscribirse a 8 bancos por separado para discursos.
3. **Ministerio de Finanzas de Japón (MOF)** — para USDJPY: la intervención cambiaria la ejecuta el MOF, no el BoJ. Sin RSS confiable, pero es la fuente primaria cuando USDJPY se mueve 300 pips en un minuto.
4. **White House / Presidential Documents** (vía Federal Register) — para shocks de política comercial que golpean oro y dólar simultáneamente.

---

## 🥇 Listado GOLD (XAUUSD) — mayor a menor impacto

| # | Fuente | Por qué / Feed |
|---|--------|----------------|
| 1 | **Federal Reserve** (FOMC, press) | Expectativas de tasa real = driver #1 del oro. `federalreserve.gov/feeds/press_monetary.xml` |
| 2 | **BLS** (CPI, NFP, PPI, salarios) | Datos que mueven la Fed. `bls.gov/feed/bls_latest.rss` (UA de browser) |
| 3 | **BEA** (Core PCE, GDP) | El PCE es el indicador de inflación preferido de la Fed. `bea.gov/news/rss` |
| 4 | **U.S. Treasury** (subastas, deuda, yields) | Yields reales ↔ oro (correlación inversa). Vía Federal Register RSS |
| 5 | **Federal Register / Presidential Docs** | Tarifas, sanciones, órdenes ejecutivas → flujo safe-haven |
| 6 | **World Gold Council** | Demanda de bancos centrales (PBoC, etc.), flujos ETF — el comprador marginal del oro hoy. Sin RSS propio: scraping o newsletter |
| 7 | **CME Group** (márgenes COMEX, contratos) | Hikes de margen en GC fuerzan liquidaciones — movimientos técnicos bruscos |
| 8 | **CFTC COT** | Posicionamiento especulativo en futuros de oro — contrarian en extremos. `cftc.gov/RSS/RSSGP/rssgp.xml` + reportes semanales |
| 9 | **LBMA** | Benchmarks, reformas del mercado físico londinense. Sin RSS: página de news |
| 10 | **Geopolítica** (Reuters/AP commodities) | El oro es safe-haven: conflictos lo mueven más que datos de rutina |

## 💱 Listado FX — mayor a menor impacto

| # | Fuente | Por qué / Feed |
|---|--------|----------------|
| 1 | **Federal Reserve** | El USD es ~88% de todo FX. `press_monetary.xml` |
| 2 | **BLS** (CPI, NFP) | Los dos datos que más mueven USD en el día. `bls_latest.rss` |
| 3 | **BEA** (PCE, GDP) | `bea.gov/news/rss` |
| 4 | **ECB** | EURUSD = par más líquido del mundo. `mid.ecb.europa.eu/rss/mid.xml` |
| 5 | **U.S. Treasury + OFAC** (vía Federal Register) | Sanciones congelan/mueven monedas enteras (RUB, etc.) |
| 6 | **BoJ + MOF** | USDJPY: intervención directa y sorpresas de política (YCC). `boj.or.jp/en/rss/whatsnew.xml` |
| 7 | **BoE** | GBP, el par más volátil de los majors. `bankofengland.co.uk/rss/news` |
| 8 | **SNB** | CHF: historial de shocks (techo EURCHF 2015). `snb.ch/public/rss/en/news` |
| 9 | **BIS central bank speeches** | Un feed para discursos de todos los BCs: `bis.org/doclist/cbspeeches.rss` |
| 10 | **RBA / BoC / RBNZ** | Según pares AUD/CAD/NZD que se operen |
| 11 | **CFTC COT (FX)** | Posicionamiento en futuros de divisas — extremos = reversals |
| 12 | **IMF** | Crisis de balanza de pagos en EM, rescates que mueven pares exóticos |

**Regla práctica de solapamiento:** Fed + BLS + BEA + Treasury están en ambas listas porque el USD es el denominador común — configurar esos 4 feeds una sola vez y etiquetarlos como `us_macro` + `gold` + `fx` en macrorss.
