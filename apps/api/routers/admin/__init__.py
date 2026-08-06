from fastapi import APIRouter

from apps.api.routers.admin.connector_definitions import router as definitions_router
from apps.api.routers.admin.connector_instances import router as instances_router
from apps.api.routers.admin.connector_runs import router as runs_router
from apps.api.routers.admin.platform_accounts import router as accounts_router
from apps.api.routers.admin.platform_risk_events import router as risk_events_router

router = APIRouter(prefix="/api/v1/admin")
router.include_router(definitions_router)
router.include_router(instances_router)
router.include_router(accounts_router)
router.include_router(runs_router)
router.include_router(risk_events_router)

__all__ = ["router"]
