from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from uuid import UUID

from packages.clustering.reprocessing import ClusteringReprocessService
from packages.database.session import get_async_sessionmaker


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("time range must include timezone")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded M3 clustering reprocessing. Defaults to dry-run."
    )
    parser.add_argument("--signal-id", action="append", type=UUID, dest="signal_ids")
    parser.add_argument("--from", type=_aware_datetime, dest="time_from")
    parser.add_argument("--to", type=_aware_datetime, dest="time_to")
    parser.add_argument("--algorithm-version", required=True)
    parser.add_argument("--embedding-version")
    parser.add_argument("--max-items", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required together with --apply. Confirms the bounded target explicitly.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        summary = await ClusteringReprocessService(session).reprocess(
            signal_ids=args.signal_ids,
            time_from=args.time_from,
            time_to=args.time_to,
            algorithm_version=args.algorithm_version,
            embedding_version=args.embedding_version,
            max_items=args.max_items,
            actor=args.actor,
            apply=args.apply,
            confirmed=args.confirm,
        )
        print(
            json.dumps(
                ClusteringReprocessService.summary_payload(summary),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
        return 1 if summary.failed else 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - CLI returns a bounded sanitized error summary.
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
