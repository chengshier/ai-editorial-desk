from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m4b import (
    ClaimNoteUpdate,
    ClaimVerificationRequest,
    EventEvidenceResponse,
    EventUnknownCreate,
    EventUnknownResponse,
    EventUnknownUpdate,
    EvidenceClaimResponse,
    EvidenceExtractionRequest,
    EvidenceExtractionResponse,
    EvidenceSourceAttach,
    EvidenceSourceResponse,
    HumanClaimCreate,
)
from packages.ai_gateway.errors import AIGatewayError
from packages.connector_management.exceptions import ResourceNotFoundError
from packages.evidence.errors import EvidenceAIError
from packages.evidence.services import (
    ClaimEvidenceView,
    EventEvidenceService,
    EvidenceExtractionService,
)

router = APIRouter(
    prefix="/events",
    tags=["admin-evidence"],
    dependencies=[Depends(require_admin_token)],
)
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("/{event_id}/evidence", response_model=EventEvidenceResponse)
async def get_event_evidence(event_id: UUID) -> EventEvidenceResponse:
    view = await EventEvidenceService().get_evidence(event_id)
    return EventEvidenceResponse(
        event_id=view.event_id,
        claims=[_claim_response(item) for item in view.claims],
        unknowns=[EventUnknownResponse.model_validate(item) for item in view.unknowns],
    )


@router.post(
    "/{event_id}/evidence/extract",
    response_model=EvidenceExtractionResponse,
)
async def extract_event_evidence(
    event_id: UUID,
    payload: EvidenceExtractionRequest,
    actor: Actor,
) -> EvidenceExtractionResponse:
    try:
        outcome = await EvidenceExtractionService().extract(
            event_id=event_id,
            actor=actor,
            apply=payload.apply,
            signal_ids=payload.signal_ids,
            max_signals=payload.max_signals,
            max_chars_per_signal=payload.max_chars_per_signal,
            max_total_chars=payload.max_total_chars,
        )
    except AIGatewayError as exc:
        raise EvidenceAIError(exc.code.value, exc.message) from exc
    return EvidenceExtractionResponse(
        run_id=outcome.run_id,
        ai_invocation_id=outcome.ai_invocation_id,
        mode=outcome.mode,
        status=outcome.status,
        claim_count=outcome.claim_count,
        unknown_count=outcome.unknown_count,
        invalid_item_count=outcome.invalid_item_count,
        invalid_codes=list(outcome.invalid_codes),
        signal_count=outcome.signal_count,
        character_count=outcome.character_count,
        truncated=outcome.truncated,
        truncated_signal_ids=list(outcome.truncated_signal_ids),
    )


@router.post(
    "/{event_id}/claims",
    response_model=EvidenceClaimResponse,
    status_code=201,
)
async def create_human_claim(
    event_id: UUID,
    payload: HumanClaimCreate,
    actor: Actor,
) -> EvidenceClaimResponse:
    service = EventEvidenceService()
    claim = await service.create_human_claim(
        event_id=event_id,
        actor=actor,
        claim_text=payload.claim_text,
        claim_type=payload.claim_type,
        sources=[(item.signal_id, item.role) for item in payload.sources],
        editor_note=payload.editor_note,
    )
    return _claim_response(await _find_claim_view(service, event_id, claim.id))


@router.get("/{event_id}/claims", response_model=list[EvidenceClaimResponse])
async def list_event_claims(event_id: UUID) -> list[EvidenceClaimResponse]:
    view = await EventEvidenceService().get_evidence(event_id)
    return [_claim_response(item) for item in view.claims]


@router.get(
    "/{event_id}/claims/{claim_id}",
    response_model=EvidenceClaimResponse,
)
async def get_event_claim(event_id: UUID, claim_id: UUID) -> EvidenceClaimResponse:
    service = EventEvidenceService()
    return _claim_response(await _find_claim_view(service, event_id, claim_id))


@router.post(
    "/{event_id}/claims/{claim_id}/sources",
    response_model=EvidenceClaimResponse,
)
async def attach_claim_source(
    event_id: UUID,
    claim_id: UUID,
    payload: EvidenceSourceAttach,
    actor: Actor,
) -> EvidenceClaimResponse:
    service = EventEvidenceService()
    await service.attach_source(
        event_id=event_id,
        claim_id=claim_id,
        signal_id=payload.signal_id,
        role=payload.role,
        actor=actor,
    )
    return _claim_response(await _find_claim_view(service, event_id, claim_id))


@router.delete(
    "/{event_id}/claims/{claim_id}/sources/{signal_id}",
    status_code=204,
)
async def remove_claim_source(
    event_id: UUID,
    claim_id: UUID,
    signal_id: UUID,
    actor: Actor,
) -> Response:
    await EventEvidenceService().remove_source(
        event_id=event_id,
        claim_id=claim_id,
        signal_id=signal_id,
        actor=actor,
    )
    return Response(status_code=204)


@router.post(
    "/{event_id}/claims/{claim_id}/verify",
    response_model=EvidenceClaimResponse,
)
async def verify_claim(
    event_id: UUID,
    claim_id: UUID,
    payload: ClaimVerificationRequest,
    actor: Actor,
) -> EvidenceClaimResponse:
    service = EventEvidenceService()
    await service.verify_claim(
        event_id=event_id,
        claim_id=claim_id,
        verification_state=payload.verification_state,
        reason=payload.reason,
        actor=actor,
    )
    return _claim_response(await _find_claim_view(service, event_id, claim_id))


@router.patch(
    "/{event_id}/claims/{claim_id}",
    response_model=EvidenceClaimResponse,
)
async def update_claim_note(
    event_id: UUID,
    claim_id: UUID,
    payload: ClaimNoteUpdate,
    actor: Actor,
) -> EvidenceClaimResponse:
    service = EventEvidenceService()
    await service.update_claim_note(
        event_id=event_id,
        claim_id=claim_id,
        editor_note=payload.editor_note,
        actor=actor,
    )
    return _claim_response(await _find_claim_view(service, event_id, claim_id))


@router.get("/{event_id}/unknowns", response_model=list[EventUnknownResponse])
async def list_event_unknowns(event_id: UUID) -> list[EventUnknownResponse]:
    view = await EventEvidenceService().get_evidence(event_id)
    return [EventUnknownResponse.model_validate(item) for item in view.unknowns]


@router.post(
    "/{event_id}/unknowns",
    response_model=EventUnknownResponse,
    status_code=201,
)
async def create_event_unknown(
    event_id: UUID,
    payload: EventUnknownCreate,
    actor: Actor,
) -> EventUnknownResponse:
    unknown = await EventEvidenceService().create_unknown(
        event_id=event_id,
        unknown_text=payload.unknown_text,
        actor=actor,
    )
    return EventUnknownResponse.model_validate(unknown)


@router.patch(
    "/{event_id}/unknowns/{unknown_id}",
    response_model=EventUnknownResponse,
)
async def update_event_unknown(
    event_id: UUID,
    unknown_id: UUID,
    payload: EventUnknownUpdate,
    actor: Actor,
) -> EventUnknownResponse:
    unknown = await EventEvidenceService().update_unknown(
        event_id=event_id,
        unknown_id=unknown_id,
        status=payload.status,
        actor=actor,
        resolution_note=payload.resolution_note,
        resolved_by_claim_id=payload.resolved_by_claim_id,
    )
    return EventUnknownResponse.model_validate(unknown)


async def _find_claim_view(
    service: EventEvidenceService,
    event_id: UUID,
    claim_id: UUID,
) -> ClaimEvidenceView:
    view = await service.get_evidence(event_id)
    for item in view.claims:
        if item.claim.id == claim_id:
            return item
    raise ResourceNotFoundError("Evidence Claim 不存在")


def _claim_response(view: ClaimEvidenceView) -> EvidenceClaimResponse:
    response = EvidenceClaimResponse.model_validate(view.claim)
    return response.model_copy(
        update={
            "sources": [
                EvidenceSourceResponse(
                    signal_id=item.signal_id,
                    role=item.role,
                    title=item.title,
                    platform=item.platform,
                    author_name=item.author_name,
                    published_at=item.published_at,
                    collected_at=item.collected_at,
                    original_url=item.original_url,
                    canonical_url=item.canonical_url,
                )
                for item in view.sources
            ]
        }
    )
