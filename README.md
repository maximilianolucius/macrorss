# MacroRSS

Agregación y procesamiento de feeds RSS macroeconómicos.

> **Estado: esqueleto inicial.** El repo está creado con la estructura y el
> tooling, pero todavía no hay lógica de negocio. El alcance concreto (fuentes,
> parsing, almacenamiento, salida) se define en `doc/`.

## Estructura

```
macrorss/          Paquete Python (código de la aplicación)
tests/             Tests con pytest
deploy/            Scripts de despliegue, systemd units, Docker, cron
doc/               Documentación, decisiones de diseño, notas
pyproject.toml     Metadatos, dependencias y config de tooling
```

## Requisitos

- Python >= 3.11

## Instalación (desarrollo)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Uso

```bash
macrorss --help
# equivalente:
python -m macrorss --help
```

## Desarrollo

```bash
pytest            # tests
ruff check .      # lint
ruff format .     # formato
mypy macrorss     # tipos
```

## Licencia

MIT — ver [LICENSE](LICENSE).
