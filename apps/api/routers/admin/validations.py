from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_actor_id, require_admin_token
from apps.api.schemas.m1d import ValidationCreate, ValidationPage, ValidationResponse
from packages.database.session import get_database_session
from packages.scheduling.admin import ConnectorValidationService

router = APIRouter(
    prefix="/connector-validations",
    tags=["admin-connector-validations"],
    dependencies=[Depends(require_admin_token)],
)
Session = Annotated[AsyncSession, Depends(get_database_session)]
Actor = Annotated[str, Depends(require_actor_id)]


@router.get("", response_model=ValidationPage)
async def list_validations(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    connector_type: str | None = None,
    platform: str | None = None,
) -> ValidationPage:
    result = await ConnectorValidationService(session).list(
        page=page,
        page_size=page_size,
        connector_type=connector_type,
        platform=platform,
    )
    return ValidationPage(
        items=[ValidationResponse.from_orm_model(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_next=result.has_next,
    )


@router.post("", response_model=ValidationResponse, status_code=201)
async def create_validation(
    payload: ValidationCreate, session: Session, actor: Actor
) -> ValidationResponse:
    record = await ConnectorValidationService(session).record(
        connector_type=payload.connector_type,
        platform=payload.platform,
        implementation_version=payload.implementation_version,
        environment=payload.environment,
        status=payload.status,
        actor=actor,
        notes=payload.notes,
        safe_evidence=payload.safe_evidence,
        real_smoke_test=payload.real_smoke_test,
    )
    return ValidationResponse.from_orm_model(record)
