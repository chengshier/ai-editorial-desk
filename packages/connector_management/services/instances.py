from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connector_management.exceptions import ConflictError, ResourceNotFoundError
from packages.connector_management.repositories import (
    AuditLogRepository,
    ConnectorDefinitionRepository,
    ConnectorInstanceRepository,
    Page,
)
from packages.connector_management.validation import (
    validate_connector_config,
    validate_schedule_config,
)
from packages.database.models import ConnectorInstance

INSTANCE_CONFIGURED = "configured"
INSTANCE_ACTIVE = "active"
INSTANCE_INACTIVE = "inactive"
INSTANCE_ARCHIVED = "archived"


def _instance_snapshot(instance: ConnectorInstance) -> dict[str, Any]:
    return {
        "definition_id": str(instance.definition_id),
        "name": instance.name,
        "enabled": instance.enabled,
        "status": instance.status,
        "config": instance.config,
        "schedule_config": instance.schedule_config,
        "credential_configured": bool(instance.credential_ref),
        "config_version": instance.config_version,
        "updated_by": instance.updated_by,
    }


class ConnectorInstanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConnectorInstanceRepository(session)
        self.definitions = ConnectorDefinitionRepository(session)
        self.audit = AuditLogRepository(session)

    async def create(
        self,
        *,
        definition_id: UUID,
        name: str,
        config: dict[str, Any],
        schedule_config: dict[str, Any],
        actor: str,
    ) -> ConnectorInstance:
        normalized_name = name.strip()
        async with self.session.begin():
            definition = await self.definitions.get(definition_id)
            if definition is None:
                raise ResourceNotFoundError("连接器定义不存在")
            if not definition.is_enabled:
                raise ConflictError("连接器定义当前已停用")
            if await self.repository.get_by_name(definition_id, normalized_name) is not None:
                raise ConflictError("同一连接器定义下实例名称已存在")
            validate_connector_config(definition.config_schema, config)
            validate_schedule_config(schedule_config)
            instance = ConnectorInstance(
                definition_id=definition_id,
                name=normalized_name,
                enabled=False,
                status=INSTANCE_CONFIGURED,
                config=config,
                schedule_config=schedule_config,
                config_version=1,
                updated_by=actor,
                definition=definition,
            )
            self.repository.add(instance)
            await self.session.flush()
            self.audit.add(
                entity_type="connector_instance",
                entity_id=instance.id,
                action="create",
                actor=actor,
                before_data={},
                after_data=_instance_snapshot(instance),
            )
        return instance

    async def get(self, instance_id: UUID) -> ConnectorInstance:
        instance = await self.repository.get(instance_id)
        if instance is None:
            raise ResourceNotFoundError("连接器实例不存在")
        return instance

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        definition_id: UUID | None,
        enabled: bool | None,
        status: str | None,
    ) -> Page[ConnectorInstance]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            definition_id=definition_id,
            enabled=enabled,
            status=status,
        )

    async def update(
        self,
        *,
        instance_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> ConnectorInstance:
        async with self.session.begin():
            instance = await self.repository.get(instance_id)
            if instance is None:
                raise ResourceNotFoundError("连接器实例不存在")
            if instance.status == INSTANCE_ARCHIVED:
                raise ConflictError("已归档实例不可修改")
            before = _instance_snapshot(instance)
            config_changed = False

            if "name" in changes:
                normalized_name = str(changes["name"]).strip()
                duplicate = await self.repository.get_by_name(
                    instance.definition_id, normalized_name
                )
                if duplicate is not None and duplicate.id != instance.id:
                    raise ConflictError("同一连接器定义下实例名称已存在")
                instance.name = normalized_name

            if "config" in changes:
                new_config = dict(changes["config"])
                validate_connector_config(instance.definition.config_schema, new_config)
                if instance.config != new_config:
                    instance.config = new_config
                    config_changed = True

            if "schedule_config" in changes:
                new_schedule = dict(changes["schedule_config"])
                validate_schedule_config(new_schedule)
                if instance.schedule_config != new_schedule:
                    instance.schedule_config = new_schedule
                    config_changed = True

            after_candidate = _instance_snapshot(instance)
            actual_changed = before != after_candidate
            if not actual_changed:
                return instance
            if config_changed:
                instance.config_version += 1
            instance.updated_by = actor
            self.audit.add(
                entity_type="connector_instance",
                entity_id=instance.id,
                action="update",
                actor=actor,
                before_data=before,
                after_data=_instance_snapshot(instance),
            )
        return instance

    async def enable(self, *, instance_id: UUID, actor: str) -> ConnectorInstance:
        return await self._set_lifecycle(
            instance_id=instance_id,
            actor=actor,
            action="enable",
            enabled=True,
            status=INSTANCE_ACTIVE,
        )

    async def disable(self, *, instance_id: UUID, actor: str) -> ConnectorInstance:
        return await self._set_lifecycle(
            instance_id=instance_id,
            actor=actor,
            action="disable",
            enabled=False,
            status=INSTANCE_INACTIVE,
        )

    async def archive(self, *, instance_id: UUID, actor: str) -> ConnectorInstance:
        return await self._set_lifecycle(
            instance_id=instance_id,
            actor=actor,
            action="archive",
            enabled=False,
            status=INSTANCE_ARCHIVED,
        )

    async def _set_lifecycle(
        self,
        *,
        instance_id: UUID,
        actor: str,
        action: str,
        enabled: bool,
        status: str,
    ) -> ConnectorInstance:
        async with self.session.begin():
            instance = await self.repository.get(instance_id)
            if instance is None:
                raise ResourceNotFoundError("连接器实例不存在")
            if instance.status == INSTANCE_ARCHIVED:
                if action == "archive":
                    return instance
                raise ConflictError("已归档实例不可重新启用或停用")
            before = _instance_snapshot(instance)
            if instance.enabled == enabled and instance.status == status:
                return instance
            instance.enabled = enabled
            instance.status = status
            instance.updated_by = actor
            self.audit.add(
                entity_type="connector_instance",
                entity_id=instance.id,
                action=action,
                actor=actor,
                before_data=before,
                after_data=_instance_snapshot(instance),
            )
        return instance
