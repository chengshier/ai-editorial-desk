from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from packages.connector_management.services import PlatformAccountService
from packages.connectors.mediacrawler_adapter.browser_runtime import (
    LocalBrowserRuntimeError,
    LocalBrowserRuntimeManager,
    LocalBrowserRuntimeSnapshot,
)
from packages.database.models import PlatformAccount
from packages.database.session import get_database_session

router = APIRouter(
    prefix="/platform-accounts",
    tags=["admin-local-browser-runtime"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


class BrowserRuntimeResponse(BaseModel):
    status: str
    enabled: bool
    browser_name: str | None
    cdp_ready: bool
    managed_by_api: bool
    profile_configured: bool
    profile_ready: bool
    can_start: bool
    can_stop: bool
    can_open_login: bool
    cdp_host: str
    cdp_port: int
    message: str


async def _account(account_id: UUID, session: Session) -> PlatformAccount:
    return await PlatformAccountService(session).get(account_id)


def _response(snapshot: LocalBrowserRuntimeSnapshot) -> BrowserRuntimeResponse:
    return BrowserRuntimeResponse(
        status=snapshot.status,
        enabled=snapshot.enabled,
        browser_name=snapshot.browser_name,
        cdp_ready=snapshot.cdp_ready,
        managed_by_api=snapshot.managed_by_api,
        profile_configured=snapshot.profile_configured,
        profile_ready=snapshot.profile_ready,
        can_start=snapshot.can_start,
        can_stop=snapshot.can_stop,
        can_open_login=snapshot.can_open_login,
        cdp_host=snapshot.cdp_host,
        cdp_port=snapshot.cdp_port,
        message=snapshot.message,
    )


@router.get("/{account_id}/browser-runtime", response_model=BrowserRuntimeResponse)
async def browser_runtime_status(account_id: UUID, session: Session) -> BrowserRuntimeResponse:
    account = await _account(account_id, session)
    snapshot = LocalBrowserRuntimeManager().status(
        account_id=account.id,
        profile_ref=account.browser_profile_ref,
    )
    return _response(snapshot)


@router.post("/{account_id}/browser-runtime/start", response_model=BrowserRuntimeResponse)
async def start_browser_runtime(
    account_id: UUID,
    session: Session,
    actor: Actor,
) -> BrowserRuntimeResponse:
    del actor
    account = await _account(account_id, session)
    try:
        snapshot = await LocalBrowserRuntimeManager().start(
            account_id=account.id,
            profile_ref=account.browser_profile_ref,
        )
    except LocalBrowserRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(snapshot)


@router.post("/{account_id}/browser-runtime/open-login", response_model=BrowserRuntimeResponse)
async def open_browser_login(
    account_id: UUID,
    session: Session,
    actor: Actor,
) -> BrowserRuntimeResponse:
    del actor
    account = await _account(account_id, session)
    try:
        snapshot = await LocalBrowserRuntimeManager().open_login(
            account_id=account.id,
            profile_ref=account.browser_profile_ref,
            platform=account.platform,
        )
    except LocalBrowserRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(snapshot)


@router.post("/{account_id}/browser-runtime/stop", response_model=BrowserRuntimeResponse)
async def stop_browser_runtime(
    account_id: UUID,
    session: Session,
    actor: Actor,
) -> BrowserRuntimeResponse:
    del actor
    account = await _account(account_id, session)
    try:
        snapshot = await LocalBrowserRuntimeManager().stop(
            account_id=account.id,
            profile_ref=account.browser_profile_ref,
        )
    except LocalBrowserRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(snapshot)
