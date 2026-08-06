from sqlalchemy.dialects.postgresql import JSONB

from packages.database.base import Base
from packages.database.models import ConnectorRun

EXPECTED_TABLES = {
    "connector_definitions",
    "connector_instances",
    "platform_accounts",
    "connector_runs",
    "connector_checkpoints",
    "platform_risk_events",
}


def test_all_m1a_models_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_connector_run_metadata_uses_jsonb_column_alias() -> None:
    column = ConnectorRun.__table__.c.metadata

    assert isinstance(column.type, JSONB)
    assert ConnectorRun.run_metadata.property.columns[0].name == "metadata"
