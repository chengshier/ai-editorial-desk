from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.database.models import ScheduleType

MIN_INTERVAL_SECONDS = 300
MAX_CRON_SEARCH_MINUTES = 60 * 24 * 366


class ScheduleSpecError(ValueError):
    """Raised when an M1 scheduler expression is unsafe or unsupported."""


def _parse_part(value: str, minimum: int, maximum: int) -> set[int]:
    if value == "*":
        return set(range(minimum, maximum + 1))
    if value.startswith("*/"):
        try:
            step = int(value[2:])
        except ValueError as exc:
            raise ScheduleSpecError("cron 步长必须为整数") from exc
        if step < 1:
            raise ScheduleSpecError("cron 步长必须大于 0")
        return set(range(minimum, maximum + 1, step))
    if "-" in value:
        start_text, end_text = value.split("-", 1)
        try:
            start, end = int(start_text), int(end_text)
        except ValueError as exc:
            raise ScheduleSpecError("cron 范围必须为整数") from exc
        if start > end or start < minimum or end > maximum:
            raise ScheduleSpecError("cron 范围超出允许值")
        return set(range(start, end + 1))
    try:
        number = int(value)
    except ValueError as exc:
        raise ScheduleSpecError("cron 字段仅支持 *, */N, A-B, A,B 或整数") from exc
    if number < minimum or number > maximum:
        raise ScheduleSpecError("cron 字段超出允许值")
    return {number}


def _parse_field(value: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in value.split(","):
        values.update(_parse_part(part.strip(), minimum, maximum))
    if not values:
        raise ScheduleSpecError("cron 字段不能为空")
    return values


def _cron_fields(expression: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = expression.split()
    if len(parts) != 5:
        raise ScheduleSpecError("M1 cron 仅支持标准 5 字段表达式")
    return (
        _parse_field(parts[0], 0, 59),
        _parse_field(parts[1], 0, 23),
        _parse_field(parts[2], 1, 31),
        _parse_field(parts[3], 1, 12),
        _parse_field(parts[4], 0, 6),
    )


def _next_cron(expression: str, reference: datetime, zone: ZoneInfo) -> datetime:
    minutes, hours, month_days, months, weekdays = _cron_fields(expression)
    local = reference.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(MAX_CRON_SEARCH_MINUTES):
        cron_weekday = (local.weekday() + 1) % 7
        if (
            local.minute in minutes
            and local.hour in hours
            and local.day in month_days
            and local.month in months
            and cron_weekday in weekdays
        ):
            return local.astimezone(UTC)
        local += timedelta(minutes=1)
    raise ScheduleSpecError("cron 在一年搜索窗口内没有下一次执行时间")


def validate_schedule_spec(
    *,
    schedule_type: ScheduleType,
    interval_seconds: int | None,
    cron_expression: str | None,
    timezone_name: str,
    reference: datetime | None = None,
) -> None:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleSpecError("未知时区") from exc
    if schedule_type is ScheduleType.INTERVAL:
        if interval_seconds is None or interval_seconds < MIN_INTERVAL_SECONDS:
            raise ScheduleSpecError("interval 最低频率为 300 秒")
        if cron_expression:
            raise ScheduleSpecError("interval 调度不能同时设置 cron_expression")
        return
    if interval_seconds is not None:
        raise ScheduleSpecError("cron 调度不能同时设置 interval_seconds")
    if not cron_expression:
        raise ScheduleSpecError("cron 调度必须提供 cron_expression")
    probe = reference or datetime.now(UTC)
    first = _next_cron(cron_expression, probe, zone)
    second = _next_cron(cron_expression, first, zone)
    if (second - first).total_seconds() < MIN_INTERVAL_SECONDS:
        raise ScheduleSpecError("cron 频率不能高于每 5 分钟一次")


def calculate_next_run(
    *,
    schedule_type: ScheduleType,
    interval_seconds: int | None,
    cron_expression: str | None,
    timezone_name: str,
    reference: datetime,
) -> datetime:
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ScheduleSpecError("reference 必须包含时区")
    validate_schedule_spec(
        schedule_type=schedule_type,
        interval_seconds=interval_seconds,
        cron_expression=cron_expression,
        timezone_name=timezone_name,
        reference=reference,
    )
    if schedule_type is ScheduleType.INTERVAL:
        assert interval_seconds is not None
        return reference.astimezone(UTC) + timedelta(seconds=interval_seconds)
    assert cron_expression is not None
    return _next_cron(cron_expression, reference, ZoneInfo(timezone_name))
