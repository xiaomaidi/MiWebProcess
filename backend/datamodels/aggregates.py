"""Safe cross-record aggregate functions for formula fields.

These functions are injected into the formula evaluator so a formula field can
derive values from child/related records without allowing arbitrary ORM access.
"""
from __future__ import annotations

from typing import Any, Callable

from .models import DataModel, DataRecord

MAX_RELATED_ROWS = 5000


def _target_model(source: DataModel, model_name: str) -> DataModel | None:
    return DataModel.objects.filter(app=source.app, name=str(model_name or "")).first()


def _matching_rows(
    source: DataModel,
    model_name: str,
    filter_field: str | None = None,
    filter_value: Any = None,
) -> list[dict]:
    target = _target_model(source, model_name)
    if target is None:
        return []
    rows = DataRecord.objects.filter(model=target).values_list("data", flat=True)[:MAX_RELATED_ROWS]
    if not filter_field:
        return [row for row in rows if isinstance(row, dict)]
    return [
        row for row in rows
        if isinstance(row, dict) and str(row.get(str(filter_field))) == str(filter_value)
    ]


def _numbers(rows: list[dict], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def aggregate_functions(source: DataModel) -> dict[str, Callable[..., Any]]:
    """Return aggregate callables bound to the current model's application."""

    def sum_related(model_name: str, field: str, filter_field: str | None = None, filter_value: Any = None) -> float:
        return sum(_numbers(_matching_rows(source, model_name, filter_field, filter_value), field))

    def count_related(model_name: str, filter_field: str | None = None, filter_value: Any = None) -> int:
        return len(_matching_rows(source, model_name, filter_field, filter_value))

    def avg_related(model_name: str, field: str, filter_field: str | None = None, filter_value: Any = None) -> float:
        values = _numbers(_matching_rows(source, model_name, filter_field, filter_value), field)
        return sum(values) / len(values) if values else 0

    def min_related(model_name: str, field: str, filter_field: str | None = None, filter_value: Any = None) -> float:
        values = _numbers(_matching_rows(source, model_name, filter_field, filter_value), field)
        return min(values) if values else 0

    def max_related(model_name: str, field: str, filter_field: str | None = None, filter_value: Any = None) -> float:
        values = _numbers(_matching_rows(source, model_name, filter_field, filter_value), field)
        return max(values) if values else 0

    return {
        "sum_related": sum_related,
        "count_related": count_related,
        "avg_related": avg_related,
        "min_related": min_related,
        "max_related": max_related,
    }
