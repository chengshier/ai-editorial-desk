from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from packages.database.session import dispose_database, get_async_sessionmaker
from packages.validation import M5DPreflightService


def _uuid(value: str) -> UUID:
    return UUID(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only M5-D real-validation preflight")
    parser.add_argument("--platform", choices=("bilibili", "zhihu"), required=True)
    parser.add_argument("--connector-instance", type=_uuid, required=True)
    parser.add_argument("--source", type=_uuid, required=True)
    parser.add_argument("--account", type=_uuid, required=True)
    parser.add_argument("--provider-id", type=_uuid)
    parser.add_argument("--limit", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--phase", choices=("platform", "provider", "e2e"), default="e2e")
    return parser


async def _run(args: argparse.Namespace) -> int:
    factory = get_async_sessionmaker()
    try:
        async with factory() as session:
            result = await M5DPreflightService(session).run(
                platform=args.platform,
                connector_instance_id=args.connector_instance,
                source_id=args.source,
                account_id=args.account,
                requested_limit=args.limit,
                provider_id=args.provider_id,
                phase=args.phase,
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
            return 2 if result.result.value == "BLOCK" else 0
    finally:
        await dispose_database()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
