from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.ai_gateway.errors import AIErrorCode, AIGatewayError
from packages.database.models import DraftType, EditorialDraftRecord, EditorialRiskLevel
from packages.database.session import get_async_sessionmaker
from packages.editorial.errors import (
    DraftValidationError,
    UnsupportedDraftClaimError,
    UnsupportedDraftUnknownError,
)
from tests.m4d_helpers import create_m4d_context, create_mock_draft_service, valid_draft_payload


@pytest.mark.usefixtures("clean_database")
async def test_other_event_claim_and_unknown_are_rejected(db_session) -> None:  # type: ignore[no-untyped-def]
    first = await create_m4d_context(db_session, title="Target event")
    other = await create_m4d_context(db_session, title="Other event")

    wrong_claim, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(claim_id=other.claims["confirmed"].id),
    )
    with pytest.raises(UnsupportedDraftClaimError):
        await wrong_claim.generate(
            event_id=first.event.id,
            event_card_id=first.card.id,
            editorial_pack_id=first.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )

    wrong_unknown_payload = valid_draft_payload(
        claim_id=first.claims["confirmed"].id,
        unknown_id=other.unknown.id,
    )
    wrong_unknown, _calls = await create_mock_draft_service(
        db_session,
        response_data=wrong_unknown_payload,
    )
    with pytest.raises(UnsupportedDraftUnknownError):
        await wrong_unknown.generate(
            event_id=first.event.id,
            event_card_id=first.card.id,
            editorial_pack_id=first.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )


@pytest.mark.usefixtures("clean_database")
async def test_invalid_format_and_overlong_output_never_persist(db_session) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session)
    invalid_format = valid_draft_payload(claim_id=context.claims["confirmed"].id)
    invalid_format["format_key"] = "super_viral"
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data=invalid_format,
    )
    with pytest.raises(AIGatewayError) as invalid:
        await service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.STANDARD_90S,
            actor="writer",
            apply=False,
        )
    assert invalid.value.code is AIErrorCode.STRUCTURED_OUTPUT_INVALID

    overlong = valid_draft_payload(
        claim_id=context.claims["confirmed"].id,
        draft_type="short_30s",
        text="长" * 1000,
    )
    long_service, _calls = await create_mock_draft_service(
        db_session,
        response_data=overlong,
    )
    with pytest.raises(DraftValidationError):
        await long_service.generate(
            event_id=context.event.id,
            event_card_id=context.card.id,
            editorial_pack_id=context.pack.id,
            draft_type=DraftType.SHORT_30S,
            actor="writer",
            apply=False,
        )

    async with get_async_sessionmaker()() as session:
        assert await session.scalar(
            select(func.count()).select_from(EditorialDraftRecord)
        ) == 0


@pytest.mark.usefixtures("clean_database")
@pytest.mark.parametrize("risk", [EditorialRiskLevel.R0, EditorialRiskLevel.R2])
async def test_r0_and_r2_normal_candidate_path_is_available(
    db_session,
    risk: EditorialRiskLevel,
) -> None:  # type: ignore[no-untyped-def]
    context = await create_m4d_context(db_session, risk_level=risk)
    service, _calls = await create_mock_draft_service(
        db_session,
        response_data=valid_draft_payload(
            claim_id=context.claims["confirmed"].id,
            unknown_id=context.unknown.id,
        ),
    )
    outcome = await service.generate(
        event_id=context.event.id,
        event_card_id=context.card.id,
        editorial_pack_id=context.pack.id,
        draft_type=DraftType.STANDARD_90S,
        actor="writer",
        apply=True,
    )
    assert outcome.draft is not None
