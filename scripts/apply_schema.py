#!/usr/bin/env python3
"""Apply deploy/schema.sql using asyncmy. Intended for CI/bootstrap automation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


def split_sql(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


async def main() -> None:
    import asyncmy

    host = os.getenv("MACRORSS_DB_HOST", "127.0.0.1")
    port = int(os.getenv("MACRORSS_DB_PORT", "3306"))
    user = os.getenv("MACRORSS_DB_USER", "root")
    password = os.environ["MACRORSS_DB_PASSWORD"]
    connection = await asyncmy.connect(host=host, port=port, user=user, password=password, autocommit=True)
    try:
        async with connection.cursor() as cursor:
            sql = Path("deploy/schema.sql").read_text(encoding="utf-8")
            for statement in split_sql(sql):
                await cursor.execute(statement)
    finally:
        connection.close()


if __name__ == "__main__":
    asyncio.run(main())
