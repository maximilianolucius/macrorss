# Deployment

Production deployment assets for MacroRSS.

## Files

- `schema.sql` — MySQL/InnoDB schema used by the collector.
- `grants.sql.example` — minimum application grants required to apply/use the schema.
- `macrorss.service` — hardened system-level systemd unit.
- `install-systemd.sh` — helper for the `/opt/macrorss` system deployment.

No file in this directory may contain real credentials. Secrets belong in an environment file
outside Git and are covered by `.gitignore` when developing from a checkout.

## Supported deployment modes

### Hardened system service

Use `install-systemd.sh` on a dedicated Ubuntu host when root access is available. The service
runs as an unprivileged account with `Restart=always`, journald logging and filesystem hardening.

```bash
sudo ./deploy/install-systemd.sh
sudo systemctl enable --now macrorss
sudo systemctl status macrorss
journalctl -u macrorss -f
```

### User service

A workstation/non-root deployment may run from a checkout under `systemd --user`. Enable linger
if the service must start at boot without an interactive login.

```bash
systemctl --user enable --now macrorss
systemctl --user status macrorss
journalctl --user -u macrorss -f
```

The repository stores deployment assets and validation instructions, not the authoritative live
state of a particular host. Check service liveness on the target host with the relevant
`systemctl ... status macrorss` command.

## Database routing

The application can connect directly to MySQL or through ProxySQL. In the validated LAN setup,
ProxySQL is reached on port `6033`; the `macrorss` user must exist both on the backend MySQL server
and in ProxySQL's `mysql_users` table with the intended hostgroup.

Before starting the daemon:

```bash
macrorss check-config
macrorss check-db
```

See `../doc/operacion.md` for runtime inspection, spool recovery, outages and chaos checks.
