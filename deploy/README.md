# Deploy

Artefactos de despliegue y operación.

## Pendiente de definir

- Objetivo de despliegue (servidor propio, contenedor, cron local).
- Unit de systemd o timer / entrada de cron para la ingesta periódica.
- Gestión de configuración y secretos (`.env`, variables de entorno).
- Healthcheck y rotación de logs.

## Convención

Nada en este directorio debe contener credenciales. Los secretos van por
variables de entorno o ficheros ignorados por git (ver `.gitignore`).
