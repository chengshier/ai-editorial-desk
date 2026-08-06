from dataclasses import dataclass

from packages.risk_guard.models import ErrorDisposition, RiskAction


@dataclass(slots=True, frozen=True)
class RiskDecision:
    disposition: ErrorDisposition
    action: RiskAction
    reason: str


NON_RETRYABLE_MARKERS = (
    "account blocked",
    "检测到ai操作",
    "检测到自动化",
    "验证码",
    "滑块",
    "没有权限访问",
    "账号异常",
    "访问受限",
)

NON_RETRYABLE_CODES = {"-104", "403", "406", "429"}


def classify_platform_error(*, code: str | int | None, message: str) -> RiskDecision:
    normalized_code = "" if code is None else str(code).strip()
    normalized_message = message.casefold()

    if normalized_code in NON_RETRYABLE_CODES or any(
        marker.casefold() in normalized_message for marker in NON_RETRYABLE_MARKERS
    ):
        return RiskDecision(
            disposition=ErrorDisposition.MANUAL_REVIEW,
            action=RiskAction.PAUSE_ACCOUNT,
            reason="platform restriction or verification signal",
        )

    if normalized_code.startswith("5") or "timeout" in normalized_message or "超时" in message:
        return RiskDecision(
            disposition=ErrorDisposition.RETRYABLE,
            action=RiskAction.RETRY,
            reason="transient network or server error",
        )

    return RiskDecision(
        disposition=ErrorDisposition.NON_RETRYABLE,
        action=RiskAction.STOP_TASK,
        reason="unclassified error; stop safely instead of retrying blindly",
    )
