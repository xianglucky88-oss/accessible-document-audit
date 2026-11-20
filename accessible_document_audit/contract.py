from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Any

Row = dict[str, Any]


def read_rows(data: Row, field: str = "records") -> list[Row]:
    rows = data[field]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{field} must contain JSON objects")
    return rows


def text(row: Row, field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def number(row: Row, field: str, *, minimum: float | None = None) -> float:
    value = row[field]
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return float(value)


def integer(row: Row, field: str, *, minimum: int = 0) -> int:
    value = row[field]
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    return value


def flag(row: Row, field: str) -> bool:
    value = row[field]
    if type(value) is not bool:
        raise ValueError(f"{field} must be true or false")
    return value


def text_list(row: Row, field: str, *, default: list[str] | None = None) -> list[str]:
    value = row.get(field, default) if default is not None else row[field]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of text values")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must contain nonempty text values")
    return list(dict.fromkeys(value))


def index_rows(rows: list[Row], field: str) -> dict[str, Row]:
    result = {}
    for row in rows:
        key = text(row, field)
        if key in result:
            raise ValueError(f"duplicate {field}: {key}")
        result[key] = row
    return result


def apply_rows(data: Row, transform: Callable[[Row], Row]) -> list[Row]:
    return [
        {"fact_id": key, **transform(row)}
        for key, row in index_rows(read_rows(data), "id").items()
    ]
