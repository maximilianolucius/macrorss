"""Host clock synchronization health probe."""

from __future__ import annotations

import shutil
import subprocess


def ntp_synchronized() -> bool | None:
    """Return True/False when systemd timedatectl can answer, otherwise None."""
    timedatectl = shutil.which("timedatectl")
    if timedatectl is None:
        return None
    try:
        result = subprocess.run(
            [timedatectl, "show", "-p", "NTPSynchronized", "--value"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    if value in {"yes", "true", "1"}:
        return True
    if value in {"no", "false", "0"}:
        return False
    return None
