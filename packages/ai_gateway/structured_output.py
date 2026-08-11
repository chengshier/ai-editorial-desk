from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

StructuredOutputMode = Literal["json_schema", "json_object"]

STRUCTURED_OUTPUT_MODE_KEY = "structured_output_mode"
DEFAULT_STRUCTURED_OUTPUT_MODE: StructuredOutputMode = "json_schema"
STRUCTURED_OUTPUT_MODES = frozenset({"json_schema", "json_object"})


def structured_output_mode(config: Mapping[str, Any]) -> StructuredOutputMode:
    value = config.get(STRUCTURED_OUTPUT_MODE_KEY)
    if value is None:
        return DEFAULT_STRUCTURED_OUTPUT_MODE
    if not isinstance(value, str) or value not in STRUCTURED_OUTPUT_MODES:
        raise ValueError("structured_output_mode 必须是 json_schema 或 json_object")
    return cast(StructuredOutputMode, value)
