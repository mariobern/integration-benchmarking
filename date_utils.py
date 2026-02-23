"""Shared CLI date argument parsing helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


DATE_FORMAT = "%Y-%m-%d"


def _parse_date(value: str, arg_name: str):
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(f"{arg_name} must be in YYYY-MM-DD format: {value}") from exc


def _normalize_date_list(
    date_list: list[str] | tuple[str, ...] | str | None
) -> list[str] | None:
    if date_list is None:
        return None
    if isinstance(date_list, str):
        return [date_list]
    return list(date_list)


def expand_date_args(
    date_list: list[str] | tuple[str, ...] | str | None,
    start_date: Optional[str],
    end_date: Optional[str],
) -> list[str]:
    """Resolve --date list or --start-date/--end-date range into YYYY-MM-DD list."""
    normalized_date_list = _normalize_date_list(date_list)

    if normalized_date_list and (start_date or end_date):
        raise ValueError("Use either --date OR --start-date/--end-date, not both")

    if normalized_date_list:
        parsed_dates = {
            _parse_date(date_str, "--date") for date_str in normalized_date_list
        }
        return [date_obj.strftime(DATE_FORMAT) for date_obj in sorted(parsed_dates)]

    if start_date or end_date:
        if not start_date or not end_date:
            raise ValueError("--start-date and --end-date must be provided together")

        start = _parse_date(start_date, "--start-date")
        end = _parse_date(end_date, "--end-date")
        if start > end:
            raise ValueError("--start-date must be less than or equal to --end-date")

        day_count = (end - start).days + 1
        return [
            (start + timedelta(days=offset)).strftime(DATE_FORMAT)
            for offset in range(day_count)
        ]

    return []


def validate_date_args(args) -> None:
    """Validate --date list and --start-date/--end-date arguments."""
    expand_date_args(
        getattr(args, "date", None),
        getattr(args, "start_date", None),
        getattr(args, "end_date", None),
    )
