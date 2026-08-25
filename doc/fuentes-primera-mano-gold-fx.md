# Fuentes de primera mano para Gold (XAUUSD) y Forex

MacroRSS prioriza **fuentes oficiales observables directamente**. El criterio no es sólo que una
URL exista: se mide qué canal detecta primero cada evento y se conserva redundancia deliberada para
poder comparar RSS vs HTML/otros endpoints.

La configuración ejecutable está en `config/feeds.yaml`.

## Núcleo XAUUSD / USD

1. **Federal Reserve — Monetary Policy/FOMC**: driver principal de expectativas de tasa real.
2. **BLS**: CPI, Employment Situation/NFP, PPI y JOLTS.
3. **BEA**: PCE/Core PCE y GDP.
4. **U.S. Treasury directo**: `home.treasury.gov/news/press-releases`, monitorizado mediante adapter
   HTML para refunding, buybacks, TIC y otros comunicados sensibles al mercado.
5. **Federal Register — Treasury**: complemento regulatorio/OFAC; no se considera sustituto del
   canal directo del Treasury.
6. **Presidential Documents — Federal Register**: aranceles, órdenes ejecutivas y shocks de política
   comercial con potencial de mover dólar/oro.

## Núcleo FX

- Fed/BLS/BEA/Treasury: común a casi todos los majors por el rol del USD.
- ECB MID + ECB press: canales redundantes para EUR.
- BoJ + Japan MOF: política JPY e intervención (el adapter MOF todavía está pendiente).
- BoE: GBP.
- SNB: CHF.
- BoC: CAD.
- BIS speeches: agregación oficial de discursos de bancos centrales.

## Regulación / posicionamiento

- CFTC press + enforcement.
- SEC press.

COT es valioso para contexto/posicionamiento semanal, pero no debe confundirse con un feed de
headline intradía.

## Fuentes documentadas pero deshabilitadas

WGC, CME, LBMA, Japan MOF, RBA e IMF se mantienen en el catálogo con `enabled: false` hasta validar
un endpoint oficial suficientemente robusto. Una página HTML existente no se habilita sólo por ser
scrapeable: necesita adapter, fixture, test y health signal.

## Calendarios de burst polling

`config/events.yaml` contiene ventanas UTC para releases de alto impacto. Las fechas actuales se
obtuvieron de calendarios oficiales de BLS, BEA, Federal Reserve y ECB. El archivo debe renovarse
antes de expirar su última fecha; `check-config` valida su estructura.

## Regla de solapamiento

No se elimina redundancia entre canales oficiales si puede aportar latencia. Por ejemplo,
`fed-monetary` y `fed-press-all` pueden observar el mismo comunicado. MacroRSS conserva dos
`RawItem` y genera un solo `NormalizedEvent`; el contador de source-race indica qué canal ganó.
