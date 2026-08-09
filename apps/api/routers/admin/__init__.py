from fastapi import APIRouter

from apps.api.routers.admin.ai_gateway import router as ai_gateway_router
from apps.api.routers.admin.checkpoints import router as checkpoints_router
from apps.api.routers.admin.clustering import router as clustering_router
from apps.api.routers.admin.collection_budgets import router as budgets_router
from apps.api.routers.admin.collector_runtime import router as runtime_router
from apps.api.routers.admin.connector_definitions import router as definitions_router
from apps.api.routers.admin.connector_instances import router as instances_router
from apps.api.routers.admin.connector_runs import router as runs_router
from apps.api.routers.admin.drafts import router as drafts_router
from apps.api.routers.admin.editorial import router as editorial_router
from apps.api.routers.admin.embeddings import router as embeddings_router
from apps.api.routers.admin.events import router as events_router
from apps.api.routers.admin.evidence import router as evidence_router
from apps.api.routers.admin.platform_accounts import router as accounts_router
from apps.api.routers.admin.platform_risk_events import router as risk_events_router
from apps.api.routers.admin.raw_signals import router as raw_signals_router
from apps.api.routers.admin.scheduler_status import router as scheduler_status_router
from apps.api.routers.admin.schedules import router as schedules_router
from apps.api.routers.admin.sources import router as sources_router
from apps.api.routers.admin.validations import router as validations_router

router = APIRouter(prefix="/api/v1/admin")
router.include_router(definitions_router)
router.include_router(instances_router)
router.include_router(accounts_router)
router.include_router(sources_router)
router.include_router(raw_signals_router)
router.include_router(events_router)
router.include_router(evidence_router)
router.include_router(editorial_router)
router.include_router(drafts_router)
router.include_router(embeddings_router)
router.include_router(clustering_router)
router.include_router(ai_gateway_router)
router.include_router(budgets_router)
router.include_router(runtime_router)
router.include_router(runs_router)
router.include_router(checkpoints_router)
router.include_router(schedules_router)
router.include_router(scheduler_status_router)
router.include_router(validations_router)
router.include_router(risk_events_router)

__all__ = ["router"]
