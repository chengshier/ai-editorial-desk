from sqlalchemy import Enum as SqlEnum

from packages.database.models import PlatformAccount
from packages.risk_guard.models import AccountStatus


def test_orm_account_status_matches_risk_guard() -> None:
    status_type = PlatformAccount.__table__.c.status.type

    assert isinstance(status_type, SqlEnum)
    assert set(status_type.enums) == {status.value for status in AccountStatus}
