from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from packages.database.models import CollectionBudget

BUDGET_SCOPE_TYPES = frozenset({"platform", "account", "connector", "task"})


@dataclass(slots=True, frozen=True)
class BudgetReservation:
    budget_id: UUID
    usage_date: str
    reserved_items: int
    reserved_comments: int = 0


def default_budget_values(connector_type: str) -> dict[str, Any]:
    if connector_type == "manual":
        return {
            "max_runs_per_day": 500, "max_items_per_run": 1, "max_items_per_day": 500,
            "max_comments_per_run": 0, "max_comments_per_day": 0,
            "max_concurrency": 4, "timezone": "Asia/Shanghai", "enabled": True,
        }
    if connector_type == "hotlist":
        return {
            "max_runs_per_day": 48, "max_items_per_run": 50, "max_items_per_day": 2400,
            "max_comments_per_run": 0, "max_comments_per_day": 0,
            "max_concurrency": 1, "timezone": "Asia/Shanghai", "enabled": True,
        }
    return {
        "max_runs_per_day": 96, "max_items_per_run": 100, "max_items_per_day": 2000,
        "max_comments_per_run": 0, "max_comments_per_day": 0,
        "max_concurrency": 1, "timezone": "Asia/Shanghai", "enabled": True,
    }


def budget_snapshot(budget: CollectionBudget) -> dict[str, Any]:
    return {
        "scope_type": budget.scope_type,
        "scope_key": budget.scope_key,
        "max_runs_per_day": budget.max_runs_per_day,
        "max_items_per_run": budget.max_items_per_run,
        "max_items_per_day": budget.max_items_per_day,
        "max_comments_per_run": budget.max_comments_per_run,
        "max_comments_per_day": budget.max_comments_per_day,
        "max_concurrency": budget.max_concurrency,
        "timezone": budget.timezone,
        "enabled": budget.enabled,
        "updated_by": budget.updated_by,
    }
