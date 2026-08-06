import pytest

from packages.connector_management.exceptions import SchemaValidationError
from packages.connector_management.validation import (
    validate_connector_config,
    validate_schedule_config,
)


@pytest.mark.parametrize(
    "key",
    [
        "cookie",
        "access_token",
        "refresh-token",
        "Authorization",
        "apiKey",
        "password",
        "client_secret",
        "session",
        "credential",
    ],
)
def test_sensitive_config_variants_are_rejected(key: str) -> None:
    with pytest.raises(SchemaValidationError):
        validate_connector_config(
            {"type": "object", "additionalProperties": True},
            {"nested": {key: "secret-value"}},
        )


def test_schedule_bounds_and_unknown_fields_are_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        validate_schedule_config({"concurrency": 99})
    with pytest.raises(SchemaValidationError):
        validate_schedule_config({"unknown": True})


def test_valid_schedule_is_accepted() -> None:
    validate_schedule_config(
        {
            "enabled": True,
            "interval_minutes": 30,
            "timezone": "Asia/Shanghai",
            "max_items_per_run": 100,
            "comment_sample_limit": 20,
            "concurrency": 1,
            "retry_count": 1,
        }
    )
