from sqlalchemy.dialects.postgresql import JSONB

from packages.database.base import Base
from packages.database.models import ConfigurationChangeLog, ConnectorRun
from packages.database.types import SanitizedJSONB

EXPECTED_TABLES = {
    "connector_definitions",
    "connector_instances",
    "platform_accounts",
    "connector_runs",
    "connector_checkpoints",
    "platform_risk_events",
    "configuration_change_logs",
}


def test_all_models_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_connector_run_metadata_uses_sanitized_jsonb_alias() -> None:
    column = ConnectorRun.__table__.c.metadata

    assert isinstance(column.type, SanitizedJSONB)
    assert isinstance(column.type.impl, JSONB)
    assert ConnectorRun.run_metadata.property.columns[0].name == "metadata"


def test_configuration_change_log_uses_sanitized_jsonb() -> None:
    assert isinstance(ConfigurationChangeLog.__table__.c.before_data.type, SanitizedJSONB)
    assert isinstance(ConfigurationChangeLog.__table__.c.after_data.type, SanitizedJSONB)
