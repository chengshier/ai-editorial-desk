from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID

from packages.ai_gateway.connection_test import AIConnectionTester
from packages.database.models import AIProviderRecord
from packages.database.session import dispose_database, get_async_sessionmaker
from packages.validation import verify_business_invocation
from packages.validation.redaction import sanitize_validation_payload


def _uuid(value: str) -> UUID:
    return UUID(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled M5-D production-provider validation entrypoint"
    )
    parser.add_argument("--provider-id", type=_uuid, required=True)
    parser.add_argument("--model-id", type=_uuid, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--business-invocation-id", type=_uuid)
    parser.add_argument("--confirm-paid-call", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    if os.environ.get("CI"):
        print("BLOCK: production provider validation is forbidden in CI")
        return 2
    actor = args.actor.strip()
    if not actor or actor.casefold() in {"ci", "mock", "automation"}:
        print("BLOCK: an explicit human actor is required")
        return 2
    if not args.confirm_paid_call:
        print("BLOCK: add --confirm-paid-call only after provider preflight")
        return 2

    factory = get_async_sessionmaker()
    try:
        invocation_id, status, error_code = await AIConnectionTester(factory).test(
            provider_id=args.provider_id,
            model_id=args.model_id,
            actor=actor,
        )
        payload: dict[str, object] = {
            "connection_test": status,
            "connection_test_invocation_id": (
                str(invocation_id) if invocation_id else None
            ),
            "connection_test_error_code": error_code,
            "production_provider_validation": "PENDING_BUSINESS_INVOCATION",
        }
        if status != "succeeded":
            print(json.dumps(sanitize_validation_payload(payload), indent=2))
            return 2
        if args.business_invocation_id is None:
            print(json.dumps(sanitize_validation_payload(payload), indent=2))
            return 3
        async with factory() as session:
            provider = await session.get(AIProviderRecord, args.provider_id)
            if provider is None:
                payload["production_provider_validation"] = "FAIL"
                print(json.dumps(sanitize_validation_payload(payload), indent=2))
                return 2
            verified = await verify_business_invocation(
                session,
                args.business_invocation_id,
                expected_provider_key=provider.provider_key,
            )
            payload["business_invocation_id"] = str(args.business_invocation_id)
            payload["business_invocation"] = verified.to_dict()
            payload["production_provider_validation"] = (
                "PASS" if verified.result.value == "PASS" else "FAIL"
            )
            print(
                json.dumps(
                    sanitize_validation_payload(payload),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if verified.result.value == "PASS" else 2
    finally:
        await dispose_database()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
