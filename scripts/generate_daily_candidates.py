from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from packages.editorial.candidates import CandidateGenerationRequest, DailyCandidateService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply deterministic M5-B Daily Candidate Pool generation."
    )
    parser.add_argument("--business-date", type=date.fromisoformat)
    parser.add_argument("--timezone")
    parser.add_argument("--as-of", type=_datetime)
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--include-resolved", action="store_true")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--actor")
    parser.add_argument("--confirm", action="store_true")
    return parser


async def run(args: argparse.Namespace) -> dict[str, Any]:
    request = CandidateGenerationRequest(
        business_date=args.business_date,
        timezone=args.timezone,
        as_of_at=args.as_of,
        lookback_hours=args.lookback_hours,
        requested_limit=args.limit,
        include_resolved=args.include_resolved,
        include_archived=args.include_archived,
    )
    service = DailyCandidateService()
    if args.preview:
        preview = await service.preview(request)
        return {"mode": "preview", **_safe(asdict(preview))}
    if not args.actor or not args.confirm:
        raise SystemExit("Apply requires --actor and --confirm")
    outcome = await service.apply(request, actor=args.actor, confirmed=True)
    return {
        "mode": "apply",
        "reused": outcome.reused,
        "run_id": str(outcome.run.id),
        "business_date": outcome.run.business_date.isoformat(),
        "timezone": outcome.run.timezone,
        "as_of_at": outcome.run.as_of_at.isoformat(),
        "ranking_version": outcome.run.ranking_version,
        "candidate_count": outcome.run.candidate_count,
        "input_hash": outcome.run.input_hash,
    }


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, sort_keys=True))


def _datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "hex"):
        return str(value)
    return value


if __name__ == "__main__":
    main()
