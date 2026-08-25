# Documentación

Espacio para el diseño y las decisiones del proyecto.

## Pendiente de definir

- **Fuentes**: qué feeds RSS/Atom se consumen (bancos centrales, institutos de
  estadística, agencias, prensa financiera) y con qué frecuencia.
- **Ingesta**: polling vs. push, deduplicación, control de `ETag` /
  `Last-Modified`, política de reintentos y rate limiting.
- **Modelo de datos**: esquema de los ítems normalizados y almacenamiento
  (fichero, SQLite, Postgres/Timescale).
- **Procesamiento**: extracción de entidades/indicadores, clasificación,
  filtrado por relevancia macro.
- **Salida**: API, feed agregado, notificaciones, informes.
- **Operación**: scheduling, observabilidad, alertas de fallo.

## Índice

_(vacío — añadir documentos a medida que se escriban)_
