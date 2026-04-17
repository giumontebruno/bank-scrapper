from __future__ import annotations

import json
from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import date
from typing import Any, get_args, get_origin, get_type_hints


def Field(default: Any = MISSING, default_factory: Any = MISSING) -> Any:
    if default_factory is not MISSING:
        return field(default_factory=default_factory)
    if default is not MISSING:
        return field(default=default)
    return field()


class BaseModel:
    def __init_subclass__(cls) -> None:
        dataclass(cls, kw_only=True)

    def json(self) -> str:
        return json.dumps(self.dict(), ensure_ascii=False, default=_json_default)

    def dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def parse_obj(cls, payload: dict[str, Any]) -> "BaseModel":
        normalized: dict[str, Any] = {}
        type_hints = get_type_hints(cls)
        for item in fields(cls):
            if item.name not in payload:
                continue
            normalized[item.name] = _coerce_value(type_hints.get(item.name, item.type), payload[item.name])
        return cls(**normalized)


def _coerce_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if value is None:
        return None
    if annotation is date and isinstance(value, str):
        return date.fromisoformat(value)
    if origin is list and args:
        return [_coerce_value(args[0], item) for item in value]
    if origin is None:
        return value
    if type(None) in args:
        non_none = next((arg for arg in args if arg is not type(None)), Any)
        return _coerce_value(non_none, value)
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value
