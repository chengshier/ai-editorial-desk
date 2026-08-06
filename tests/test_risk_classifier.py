from packages.risk_guard.classifier import classify_platform_error
from packages.risk_guard.models import ErrorDisposition, RiskAction


def test_permission_denied_requires_manual_review() -> None:
    decision = classify_platform_error(code="-104", message="您当前登录的账号没有权限访问")

    assert decision.disposition is ErrorDisposition.MANUAL_REVIEW
    assert decision.action is RiskAction.PAUSE_ACCOUNT


def test_timeout_is_retryable() -> None:
    decision = classify_platform_error(code=None, message="request timeout")

    assert decision.disposition is ErrorDisposition.RETRYABLE
    assert decision.action is RiskAction.RETRY
