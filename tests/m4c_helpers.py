from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ai_gateway.gateway import AIGateway
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.connectors.base import RawSignal
from packages.database.models import (
    ConnectorDefinition,
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRelation,
    EventStatus,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.editorial.services import TrendService
from packages.events.services import EventService
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url
from tests.m4a_helpers import create_ai_stack, mock_factory

BASE_TIME = datetime(2026, 8, 9, 5, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 8, 9, 4, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TrendSignalSpec:
    text: str
    published_at: datetime
    platform: str = "rss"
    source_group: str = "source-a"
    relation: EventSignalRelation = EventSignalRelation.RELATED
    metrics: dict[str, float | int] | None = None


async def create_trend_context(
    session: AsyncSession,
    *,
    specs: list[TrendSignalSpec],
    title: str = "M4-C Trend Event",
    status: EventStatus = EventStatus.EMERGING,
) -> tuple[EventRecord, list[RawSignalRecord]]:
    await ConnectorDefinitionSyncService(session).sync()
    definition = await session.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.connector_type == "rss",
            ConnectorDefinition.platform == "rss",
        )
    )
    assert definition is not None
    await session.commit()

    suffix = uuid4().hex[:8]
    instance = await ConnectorInstanceService(session).create(
        definition_id=definition.id,
        name=f"M4-C RSS {suffix}",
        config={"feed_urls": [f"https://example.com/{suffix}.xml"]},
        schedule_config={},
        actor="m4c-test",
    )
    sources: dict[str, UUID] = {}
    for group in sorted({item.source_group for item in specs}):
        source = await SourceService(session).create(
            connector_instance_id=instance.id,
            name=f"M4-C {group} {suffix}",
            source_type="rss",
            mode="feed",
            scope_key=f"https://example.com/{suffix}/{group}.xml",
            external_ref=f"https://example.com/{suffix}/{group}.xml",
            config={},
            enabled=True,
            actor="m4c-test",
        )
        sources[group] = source.id

    event = await EventService(session).create(
        title=title,
        summary=None,
        category=None,
        status=status,
        primary_language="zh-CN",
        entities=[],
        keywords=[],
        actor="m4c-test",
    )

    signal_ids: list[UUID] = []
    for index, spec in enumerate(specs):
        external_id = f"m4c-{suffix}-{index}"
        raw = RawSignal(
            platform=spec.platform,
            external_id=external_id,
            url=f"https://example.com/{external_id}",
            title=f"Trend signal {index}",
            text=spec.text,
            published_at=spec.published_at,
            raw_payload={"authorization": "secret-never-for-scoring"},
            metrics=spec.metrics or {},
            language="zh-CN",
        )
        normalized = NormalizedSignal.from_connector_signal(
            source_id=sources[spec.source_group],
            connector_instance_id=instance.id,
            connector_run_id=None,
            connector_type="rss",
            signal=raw,
            canonical_url=normalize_http_url(raw.url),
        )
        ingestion = (await RawSignalService(session).ingest_many([normalized]))[0]
        signal_ids.append(ingestion.signal_id)
        await EventService(session).attach_signal(
            event_id=event.id,
            signal_id=ingestion.signal_id,
            relation=spec.relation,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.HUMAN,
            actor="m4c-test",
        )

    rows = list(
        await session.scalars(
            select(RawSignalRecord).where(RawSignalRecord.id.in_(signal_ids))
        )
    )
    by_id = {item.id: item for item in rows}
    signals = [by_id[signal_id] for signal_id in signal_ids]
    await session.commit()
    assert not session.in_transaction()
    return event, signals


async def create_trend_snapshot(event_id: UUID):
    return (
        await TrendService().calculate(
            event_id=event_id,
            window_start_at=WINDOW_START,
            window_end_at=WINDOW_END,
        )
    ).snapshot


async def create_mock_scoring_service(
    session: AsyncSession,
    *,
    response_data: dict[str, object],
):
    await create_ai_stack(
        session,
        task_key="editorial_scoring",
        capability="structured_output",
    )
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        import json

        return httpx.Response(
            200,
            json={
                "id": "editorial-mock",
                "choices": [
                    {"message": {"content": json.dumps(response_data)}}
                ],
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 20,
                    "total_tokens": 70,
                },
            },
        )

    gateway = AIGateway(
        session_factory=get_async_sessionmaker(),
        provider_factory=mock_factory(httpx.MockTransport(handler)),
    )
    from packages.editorial.services import EditorialScoringService

    return EditorialScoringService(gateway=gateway), calls


def valid_score_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "emotion": 80,
        "information_gap": 70,
        "visual_value": 60,
        "user_relevance": 75,
        "discussion": 65,
        "novelty": 55,
        "extendability": 70,
        "risk_level": "R2",
        "recommended_format": "quick_explainer",
        "model_reason": "Strong story value with evidence limits.",
        "traffic_total": 1,
    }
    payload.update(overrides)
    return payload
