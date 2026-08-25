#!/usr/bin/env bash
set -euo pipefail

ROOT=${ROOT:-/opt/macrorss}
SERVICE_USER=${SERVICE_USER:-macrorss}
ENV_DIR=${ENV_DIR:-/etc/macrorss}

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 2
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$ROOT/data" "$ENV_DIR"
install -m 0644 "$ROOT/deploy/macrorss.service" /etc/systemd/system/macrorss.service

if [[ ! -f "$ENV_DIR/macrorss.env" ]]; then
  install -m 0600 -o root -g root "$ROOT/.env.example" "$ENV_DIR/macrorss.env"
  echo "Created $ENV_DIR/macrorss.env. Set MACRORSS_DB_PASSWORD before starting." >&2
fi

systemctl daemon-reload
systemctl enable macrorss.service

echo "Install Python environment in $ROOT/.venv, edit $ENV_DIR/macrorss.env, then:"
echo "  sudo systemctl start macrorss"
