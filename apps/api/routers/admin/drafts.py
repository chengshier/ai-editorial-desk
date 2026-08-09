from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m4d import (
    DraftDetailResponse,
    DraftGenerateRequest,
    DraftGenerationResponse,
    DraftPreviewCandidateResponse,
    DraftReferenceResponse,
    DraftResponse,
    DraftRevisionRequest,
    EditorialPackCreateRequest,
    EditorialPackCreateResponse,
    EditorialPackResponse,
    EventCardCreateRequest,
    EventCardCreateResponse,
    EventCardResponse,
    HumanDraftRequest,
)
from packages.ai_gateway.errors import AIGatewayError
from packages.editorial.drafts_services import (
    DraftGenerationOutcome,
    DraftService,
    EditorialMarkdownExporter,
    EditorialPackService,
    EventCardService,
    HumanDraftReference,
)
from packages.editorial.errors import DraftAIError

router = APIRouter(
    prefix="/events",
    tags=["admin-drafts"],
    dependencies=[Depends(require_admin_token)],
)
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("/{event_id}/cards", response_model=list[EventCardResponse])
async def list_event_cards(event_id: UUID) -> list[EventCardResponse]:
    items = await EventCardService().list(event_id)
    return [EventCardResponse.model_validate(item) for item in items]


@router.post(
    "/{event_id}/cards",
    response_model=EventCardCreateResponse,
)
async def create_event_card(
    event_id: UUID,
    payload: EventCardCreateRequest,
    actor: Actor,
) -> EventCardCreateResponse:
    del actor
    card, created = await EventCardService().create(
        event_id=event_id,
        trend_snapshot_id=payload.trend_snapshot_id,
    )
    return EventCardCreateResponse(
        card=EventCardResponse.model_validate(card),
        created=created,
    )


@router.get("/{event_id}/editorial-packs", response_model=list[EditorialPackResponse])
async def list_editorial_packs(event_id: UUID) -> list[EditorialPackResponse]:
    items = await EditorialPackService().list(event_id)
    return [EditorialPackResponse.model_validate(item) for item in items]


@router.post(
    "/{event_id}/editorial-packs",
    response_model=EditorialPackCreateResponse,
)
async def create_editorial_pack(
    event_id: UUID,
    payload: EditorialPackCreateRequest,
    actor: Actor,
) -> EditorialPackCreateResponse:
    del actor
    pack, created = await EditorialPackService().create(
        event_id=event_id,
        event_card_id=payload.event_card_id,
    )
    return EditorialPackCreateResponse(
        pack=EditorialPackResponse.model_validate(pack),
        created=created,
    )


@router.get("/{event_id}/drafts", response_model=list[DraftResponse])
async def list_drafts(event_id: UUID) -> list[DraftResponse]:
    items = await DraftService().list(event_id)
    return [DraftResponse.model_validate(item) for item in items]


@router.get("/{event_id}/drafts/{draft_id}", response_model=DraftDetailResponse)
async def get_draft(event_id: UUID, draft_id: UUID) -> DraftDetailResponse:
    service = DraftService()
    draft, refs = await service.detail(event_id, draft_id)
    chain = await service.chain(event_id, draft_id)
    return DraftDetailResponse(
        draft=DraftResponse.model_validate(draft),
        claim_references=[DraftReferenceResponse.model_validate(item) for item in refs],
        version_chain=[DraftResponse.model_validate(item) for item in chain],
    )


@router.post("/{event_id}/drafts/preview", response_model=DraftGenerationResponse)
async def preview_draft(
    event_id: UUID,
    payload: DraftGenerateRequest,
    actor: Actor,
) -> DraftGenerationResponse:
    return await _generate(event_id, payload, actor, apply=False)


@router.post("/{event_id}/drafts", response_model=DraftGenerationResponse)
async def generate_draft(
    event_id: UUID,
    payload: DraftGenerateRequest,
    actor: Actor,
) -> DraftGenerationResponse:
    return await _generate(event_id, payload, actor, apply=True)


@router.post(
    "/{event_id}/drafts/manual",
    response_model=DraftResponse,
    status_code=201,
)
async def create_manual_draft(
    event_id: UUID,
    payload: HumanDraftRequest,
    actor: Actor,
) -> DraftResponse:
    draft = await DraftService().create_manual(
        event_id=event_id,
        event_card_id=payload.event_card_id,
        editorial_pack_id=payload.editorial_pack_id,
        draft_type=payload.draft_type,
        actor=actor,
        reason=payload.reason,
        body=payload.body,
        references=[
            HumanDraftReference(
                claim_id=item.claim_id,
                section_key=item.section_key,
                usage=item.usage,
            )
            for item in payload.references
        ],
        title=payload.title,
        hook=payload.hook,
        ending=payload.ending,
        interaction_question=payload.interaction_question,
    )
    return DraftResponse.model_validate(draft)


@router.post(
    "/{event_id}/drafts/{draft_id}/revisions",
    response_model=DraftResponse,
    status_code=201,
)
async def create_draft_revision(
    event_id: UUID,
    draft_id: UUID,
    payload: DraftRevisionRequest,
    actor: Actor,
) -> DraftResponse:
    draft = await DraftService().revise(
        event_id=event_id,
        parent_draft_id=draft_id,
        actor=actor,
        change_note=payload.change_note,
        body=payload.body,
        references=[
            HumanDraftReference(
                claim_id=item.claim_id,
                section_key=item.section_key,
                usage=item.usage,
            )
            for item in payload.references
        ],
        title=payload.title,
        hook=payload.hook,
        ending=payload.ending,
        interaction_question=payload.interaction_question,
    )
    return DraftResponse.model_validate(draft)


@router.get("/{event_id}/editorial-pack/export.md", response_class=PlainTextResponse)
async def export_editorial_pack_markdown(
    event_id: UUID,
    pack_id: Annotated[UUID, Query()],
    draft_id: Annotated[UUID | None, Query()] = None,
) -> PlainTextResponse:
    markdown = await EditorialMarkdownExporter().render(
        event_id=event_id,
        editorial_pack_id=pack_id,
        draft_id=draft_id,
    )
    return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8")


async def _generate(
    event_id: UUID,
    payload: DraftGenerateRequest,
    actor: str,
    *,
    apply: bool,
) -> DraftGenerationResponse:
    try:
        outcome = await DraftService().generate(
            event_id=event_id,
            event_card_id=payload.event_card_id,
            editorial_pack_id=payload.editorial_pack_id,
            draft_type=payload.draft_type,
            actor=actor,
            apply=apply,
            risk_approval_reason=payload.risk_approval_reason,
        )
    except AIGatewayError as exc:
        raise DraftAIError(exc.code.value, exc.message) from exc
    return _generation_response(outcome)


def _generation_response(outcome: DraftGenerationOutcome) -> DraftGenerationResponse:
    candidate = outcome.candidate
    candidate_response: DraftPreviewCandidateResponse | None = None
    if candidate is not None:
        candidate_response = DraftPreviewCandidateResponse(
            draft_type=candidate.draft_type,
            format_key=candidate.format_key,
            title_candidates=list(candidate.title_candidates),
            hook_candidates=list(candidate.hook_candidates),
            cover_text_candidates=list(candidate.cover_text_candidates),
            sections=[
                {
                    "section_key": section.section_key,
                    "section_kind": section.section_kind,
                    "text": section.text,
                    "citations": [
                        {
                            "claim_id": str(item.claim_id),
                            "usage": item.usage.value,
                        }
                        for item in section.citations
                    ],
                    "unknown_ids": [str(item) for item in section.unknown_ids],
                }
                for section in candidate.sections
            ],
            ending=candidate.ending,
            interaction_question=candidate.interaction_question,
        )
    return DraftGenerationResponse(
        run_id=outcome.run_id,
        ai_invocation_id=outcome.ai_invocation_id,
        mode=outcome.mode,
        status=outcome.status,
        draft=(
            DraftResponse.model_validate(outcome.draft)
            if outcome.draft is not None
            else None
        ),
        candidate=candidate_response,
        reused=outcome.reused,
    )
