from __future__ import annotations

import asyncio
import os
import socket
from os import getpid

from packages.collector_runtime import CollectorRuntime
from packages.connectors.implementations import implementation_registry
from packages.database.session import get_async_sessionmaker
from packages.scheduling import PersistentScheduler


def scheduler_instance_key() -> str:
    configured = os.getenv("SCHEDULER_INSTANCE_ID")
    if configured:
        return configured[:255]
    return f"{socket.gethostname()}:{getpid()}"[:255]


async def main() -> None:
    session_factory = get_async_sessionmaker()
    runtime = CollectorRuntime(session_factory=session_factory, registry=implementation_registry)
    scheduler = PersistentScheduler(
        session_factory=session_factory,
        runtime=runtime,
        instance_key=scheduler_instance_key(),
    )
    await scheduler.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
