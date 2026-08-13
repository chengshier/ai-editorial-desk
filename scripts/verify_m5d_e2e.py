from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from packages.database.session import dispose_database, get_async_sessionmaker
from packages.validation import sanitize_validation_payload, verify_m5d_e2e


def _uuid(value: str) -> UUID:
    return UUID(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only M5-D provenance-chain verifier")
    parser.add_argument("--collection-run-id", type=_uuid, required=True)
    parser.add_argument("--event-id", type=_uuid, required=True)
    parser.add_argument("--candidate-run-id", type=_uuid, required=True)
    parser.add_argument("--decision-id", type=_uuid, required=True)
    parser.add_argument("--draft-id", type=_uuid, required=True)
    parser.add_argument("--report", type=Path)
    return parser


async def _run(args: argparse.Namespace) -> int:
    factory = get_async_sessionmaker()
    try:
        async with factory() as session:
            result = await verify_m5d_e2e(
                session,
                collection_run_id=args.collection_run_id,
                event_id=args.event_id,
                candidate_run_id=args.candidate_run_id,
                decision_id=args.decision_id,
                draft_id=args.draft_id,
            )
            payload = sanitize_validation_payload(result.to_dict())
            rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            print(rendered)
            if args.report is not None:
                args.report.write_text(rendered + "\n", encoding="utf-8")
            return 0 if result.result == "PASS" else 2
    finally:
        await dispose_database()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
