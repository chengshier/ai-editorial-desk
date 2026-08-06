import asyncio
import json

from packages.connector_management.exceptions import DefinitionSyncError
from packages.connector_management.services import ConnectorDefinitionSyncService
from packages.database.session import dispose_database, get_async_sessionmaker


async def _run() -> int:
    session_factory = get_async_sessionmaker()
    try:
        async with session_factory() as session:
            result = await ConnectorDefinitionSyncService(session).sync()
    except DefinitionSyncError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "created": 0,
                    "updated": 0,
                    "unchanged": 0,
                    "failed": 1,
                    "message": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1
    finally:
        await dispose_database()

    print(
        json.dumps(
            {
                "status": "ok",
                "created": result.created,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "failed": result.failed,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
