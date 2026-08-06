from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.admin import (
    PlatformAccountCreate,
    PlatformAccountPage,
    PlatformAccountResponse,
    PlatformAccountTransition,
    PlatformAccountUpdate,
)
from packages.connector_management.services import PlatformAccountService
from packages.database.session import get_database_session
from packages.risk_guard.models import AccountStatus

router = APIRouter(
    prefix="/platform-accounts",
    tags=["admin-platform-accounts"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.post("", response_model=PlatformAccountResponse, status_code=201)
async def create_account(
    payload: PlatformAccountCreate,
    session: Session,
    actor: Actor,
) -> PlatformAccountResponse:
    account = await PlatformAccountService(session).create(
        connector_instance_id=payload.connector_instance_id,
        platform=payload.platform,
        display_name=payload.display_name,
        account_identifier=payload.account_identifier,
        credential_ref=payload.credential_ref,
        browser_profile_ref=payload.browser_profile_ref,
        actor=actor,
    )
    return PlatformAccountResponse.from_orm_model(account)


@router.get("", response_model=PlatformAccountPage)
async def list_accounts(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_instance_id: UUID | None = None,
    platform: str | None = None,
    status: AccountStatus | None = None,
    manual_review_required: bool | None = None,
) -> PlatformAccountPage:
    result = await PlatformAccountService(session).list(
        page=page,
        page_size=page_size,
        connector_instance_id=connector_instance_id,
        platform=platform,
        status=status,
        manual_review_required=manual_review_required,
    )
    return PlatformAccountPage(
        items=[PlatformAccountResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.get("/{account_id}", response_model=PlatformAccountResponse)
async def get_account(account_id: UUID, session: Session) -> PlatformAccountResponse:
    account = await PlatformAccountService(session).get(account_id)
    return PlatformAccountResponse.from_orm_model(account)


@router.patch("/{account_id}", response_model=PlatformAccountResponse)
async def update_account(
    account_id: UUID,
    payload: PlatformAccountUpdate,
    session: Session,
    actor: Actor,
) -> PlatformAccountResponse:
    account = await PlatformAccountService(session).update(
        account_id=account_id,
        changes=payload.model_dump(exclude_unset=True),
        actor=actor,
    )
    return PlatformAccountResponse.from_orm_model(account)


@router.post("/{account_id}/status", response_model=PlatformAccountResponse)
async def transition_account_status(
    account_id: UUID,
    payload: PlatformAccountTransition,
    session: Session,
    actor: Actor,
) -> PlatformAccountResponse:
    account = await PlatformAccountService(session).transition_status(
        account_id=account_id,
        target_status=payload.target_status,
        reason=payload.reason,
        cooldown_until=payload.cooldown_until,
        override_cooldown=payload.override_cooldown,
        actor=actor,
    )
    return PlatformAccountResponse.from_orm_model(account)
