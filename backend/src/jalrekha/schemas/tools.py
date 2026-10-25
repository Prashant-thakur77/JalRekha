from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Severity = Literal["info", "minor", "moderate", "severe"]


class GeoJSONGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Point", "Polygon"]
    coordinates: Any

    @field_validator("coordinates")
    @classmethod
    def coordinates_in_bounds(cls, value: Any) -> Any:
        def check_pair(pair: Any) -> None:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                raise ValueError("invalid coordinate pair")
            lon = float(pair[0])
            lat = float(pair[1])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("coordinate outside WGS84 bounds")

        if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
            check_pair(value)
        elif isinstance(value, (list, tuple)):
            stack = list(value)
            while stack:
                item = stack.pop()
                if isinstance(item, (list, tuple)) and item and isinstance(item[0], (int, float)):
                    check_pair(item)
                elif isinstance(item, (list, tuple)):
                    stack.extend(item)
        else:
            raise ValueError("coordinates must be an array")
        return value


class TriggerSirenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1, max_length=80)
    severity: Severity
    reason: str = Field(min_length=8, max_length=240)


class EmitCapArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=3, max_length=80)
    area: GeoJSONGeometry
    severity: Severity
    headline: str = Field(min_length=8, max_length=160)
    instruction: str = Field(min_length=12, max_length=500)


class SendLoraArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=80)
    payload_hex: str = Field(pattern=r"^[0-9A-Fa-f]{2,240}$")
    priority: Literal["normal", "high"]


TOOL_MODELS = {
    "trigger_siren": TriggerSirenArgs,
    "emit_cap": EmitCapArgs,
    "send_lora": SendLoraArgs,
}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Strict JalRekha action: {name}",
            "parameters": model.model_json_schema(),
        },
    }
    for name, model in TOOL_MODELS.items()
]
