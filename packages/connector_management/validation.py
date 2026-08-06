from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from packages.connector_management.exceptions import SchemaValidationError
from packages.database.types import is_sensitive_key

SCHEDULE_CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "enabled": {"type": "boolean", "default": False},
        "interval_minutes": {
            "type": "integer",
            "minimum": 5,
            "maximum": 10080,
            "default": 60,
        },
        "timezone": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "default": "Asia/Shanghai",
        },
        "max_items_per_run": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 100,
        },
        "comment_sample_limit": {
            "type": "integer",
            "minimum": 0,
            "maximum": 200,
            "default": 20,
        },
        "concurrency": {
            "type": "integer",
            "minimum": 1,
            "maximum": 4,
            "default": 1,
        },
        "retry_count": {
            "type": "integer",
            "minimum": 0,
            "maximum": 5,
            "default": 1,
        },
    },
}


def _json_path(error: ValidationError) -> str:
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _schema_errors(schema: dict[str, Any], value: dict[str, Any]) -> list[dict[str, str]]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaValidationError("连接器定义包含无效的 JSON Schema") from exc

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        {
            "path": _json_path(error),
            "message": error.message,
            "validator": str(error.validator),
        }
        for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    ]


def _sensitive_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if is_sensitive_key(str(key)):
                paths.append(child_path)
            paths.extend(_sensitive_paths(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_sensitive_paths(item, f"{path}[{index}]"))
    return paths


def validate_no_sensitive_fields(value: dict[str, Any], *, field_name: str) -> None:
    paths = _sensitive_paths(value)
    if paths:
        raise SchemaValidationError(
            f"{field_name} 不能包含凭据或敏感字段",
            details=[
                {
                    "path": path,
                    "message": "敏感值只能通过 credential_ref 或 browser_profile_ref 保存",
                    "validator": "sensitive_field",
                }
                for path in paths
            ],
        )


def validate_connector_config(schema: dict[str, Any], config: dict[str, Any]) -> None:
    validate_no_sensitive_fields(config, field_name="config")
    errors = _schema_errors(schema, config)
    if errors:
        raise SchemaValidationError("连接器配置未通过 Schema 校验", details=errors)


def validate_schedule_config(schedule_config: dict[str, Any]) -> None:
    validate_no_sensitive_fields(schedule_config, field_name="schedule_config")
    errors = _schema_errors(SCHEDULE_CONFIG_SCHEMA, schedule_config)
    if errors:
        raise SchemaValidationError("调度配置未通过公共 Schema 校验", details=errors)
