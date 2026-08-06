import pytest
from sqlalchemy import func, select

from packages.connector_management.exceptions import ConflictError, SchemaValidationError
from packages.connector_management.services import (
    ConnectorDefinitionSyncService,
    ConnectorInstanceService,
)
from packages.database.models import ConfigurationChangeLog, ConnectorDefinition, ConnectorRun


async def _rss_definition(db_session):  # type: ignore[no-untyped-def]
    await ConnectorDefinitionSyncService(db_session).sync()
    definition = await db_session.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.platform == "rss")
    )
    assert definition is not None
    await db_session.commit()
    return definition


@pytest.mark.usefixtures("clean_database")
async def test_instance_create_update_version_and_noop(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = await _rss_definition(db_session)
    service = ConnectorInstanceService(db_session)
    instance = await service.create(
        definition_id=definition.id,
        name="新闻 RSS",
        config={"feed_urls": ["https://example.com/feed.xml"]},
        schedule_config={"enabled": False, "interval_minutes": 30},
        actor="editor-1",
    )
    assert instance.config_version == 1
    updated = await service.update(
        instance_id=instance.id,
        changes={"config": {"feed_urls": ["https://example.com/new.xml"]}},
        actor="editor-2",
    )
    assert updated.config_version == 2
    noop = await service.update(
        instance_id=instance.id,
        changes={"config": {"feed_urls": ["https://example.com/new.xml"]}},
        actor="editor-3",
    )
    assert noop.config_version == 2
    audit_count = await db_session.scalar(
        select(func.count()).select_from(ConfigurationChangeLog)
    )
    assert audit_count == 2


@pytest.mark.usefixtures("clean_database")
async def test_instance_conflict_schema_and_sensitive_failure_leave_no_audit(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = await _rss_definition(db_session)
    definition_id = definition.id
    service = ConnectorInstanceService(db_session)
    await service.create(
        definition_id=definition_id,
        name="同名实例",
        config={"feed_urls": ["https://example.com/a.xml"]},
        schedule_config={},
        actor="editor",
    )
    with pytest.raises(ConflictError):
        await service.create(
            definition_id=definition_id,
            name="同名实例",
            config={"feed_urls": ["https://example.com/b.xml"]},
            schedule_config={},
            actor="editor",
        )
    with pytest.raises(SchemaValidationError):
        await service.create(
            definition_id=definition_id,
            name="敏感实例",
            config={"feed_urls": ["https://example.com/c.xml"], "api-key": "x"},
            schedule_config={},
            actor="editor",
        )
    count = await db_session.scalar(select(func.count()).select_from(ConfigurationChangeLog))
    assert count == 1


@pytest.mark.usefixtures("clean_database")
async def test_instance_enable_disable_archive_preserves_history(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = await _rss_definition(db_session)
    service = ConnectorInstanceService(db_session)
    instance = await service.create(
        definition_id=definition.id,
        name="可归档实例",
        config={"feed_urls": ["https://example.com/feed.xml"]},
        schedule_config={},
        actor="editor",
    )
    instance_id = instance.id
    await service.enable(instance_id=instance_id, actor="editor")
    await service.disable(instance_id=instance_id, actor="editor")
    run = ConnectorRun(
        connector_instance_id=instance_id,
        mode="feed",
        requested_limit=10,
    )
    db_session.add(run)
    await db_session.commit()
    run_id = run.id
    archived = await service.archive(instance_id=instance_id, actor="editor")
    assert archived.enabled is False
    assert archived.status == "archived"
    with pytest.raises(ConflictError):
        await service.enable(instance_id=instance_id, actor="editor")
    assert await db_session.get(ConnectorRun, run_id) is not None
