from __future__ import annotations

import asyncio
import json

from packages.database.session import dispose_database, get_async_sessionmaker
from packages.validation import MVPDoctorService


async def _run() -> int:
    factory = get_async_sessionmaker()
    try:
        async with factory() as session:
            result = await MVPDoctorService(session).run()
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
            return 2 if result.result.value == "BLOCK" else 0
    finally:
        await dispose_database()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
