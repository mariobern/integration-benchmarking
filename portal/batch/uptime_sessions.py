"""
Session-aware uptime windows by asset class.

This is a low-risk, time-of-day implementation that does NOT include holiday calendars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SessionWindow:
    session: str
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True)
class SessionDefinition:
    name: str
    timezone: ZoneInfo
    days_of_week: set[int]
    windows: list[tuple[time, time]]


def _local_window_to_utc(
    target_date: date,
    tz: ZoneInfo,
    start_t: time,
    end_t: time,
) -> tuple[datetime, datetime]:
    start_local = datetime.combine(target_date, start_t, tzinfo=tz)
    end_local = datetime.combine(target_date, end_t, tzinfo=tz)
    if end_local <= start_local:
        end_local = end_local + timedelta(days=1)
    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(
        ZoneInfo("UTC")
    )


def _weekday(d: date) -> int:
    return d.weekday()  # Monday=0, Sunday=6


def _sessions_for_us_equities(target_date: date) -> list[SessionWindow]:
    et = ZoneInfo("America/New_York")
    weekday = _weekday(target_date)
    windows: list[SessionWindow] = []

    if weekday <= 4:  # Mon-Fri
        for name, start_t, end_t in [
            ("premarket", time(4, 0), time(9, 30)),
            ("regular", time(9, 30), time(16, 0)),
            ("afterhours", time(16, 0), time(20, 0)),
        ]:
            start_utc, end_utc = _local_window_to_utc(target_date, et, start_t, end_t)
            windows.append(SessionWindow(name, start_utc, end_utc))

    # Overnight: Sunday-Thursday 8PM to 4AM (next day)
    if weekday in {6, 0, 1, 2, 3}:  # Sun-Thu
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(20, 0), time(4, 0)
        )
        windows.append(SessionWindow("overnight", start_utc, end_utc))

    return windows


def _sessions_for_eu_equities(target_date: date, tz_name: str) -> list[SessionWindow]:
    tz = ZoneInfo(tz_name)
    if _weekday(target_date) > 4:
        return []
    start_utc, end_utc = _local_window_to_utc(target_date, tz, time(9, 0), time(17, 30))
    return [SessionWindow("regular", start_utc, end_utc)]


def _sessions_for_uk_equities(target_date: date) -> list[SessionWindow]:
    tz = ZoneInfo("Europe/London")
    if _weekday(target_date) > 4:
        return []
    start_utc, end_utc = _local_window_to_utc(target_date, tz, time(8, 0), time(16, 30))
    return [SessionWindow("regular", start_utc, end_utc)]


def _sessions_for_asia_equities(
    target_date: date,
    tz_name: str,
    morning: tuple[time, time],
    afternoon: tuple[time, time],
) -> list[SessionWindow]:
    tz = ZoneInfo(tz_name)
    if _weekday(target_date) > 4:
        return []
    windows = []
    for name, (start_t, end_t) in [("regular-am", morning), ("regular-pm", afternoon)]:
        start_utc, end_utc = _local_window_to_utc(target_date, tz, start_t, end_t)
        windows.append(SessionWindow(name, start_utc, end_utc))
    return windows


def _sessions_for_fx(target_date: date) -> list[SessionWindow]:
    et = ZoneInfo("America/New_York")
    weekday = _weekday(target_date)
    windows: list[SessionWindow] = []

    if weekday == 5:  # Saturday
        return windows
    if weekday == 6:  # Sunday: 5PM -> midnight
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(17, 0), time(0, 0)
        )
        windows.append(SessionWindow("regular", start_utc, end_utc))
        return windows
    if weekday == 4:  # Friday: midnight -> 5PM
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(0, 0), time(17, 0)
        )
        windows.append(SessionWindow("regular", start_utc, end_utc))
        return windows

    # Mon-Thu: full day
    start_utc, end_utc = _local_window_to_utc(target_date, et, time(0, 0), time(0, 0))
    windows.append(SessionWindow("regular", start_utc, end_utc))
    return windows


def _sessions_for_metals(target_date: date) -> list[SessionWindow]:
    et = ZoneInfo("America/New_York")
    weekday = _weekday(target_date)
    windows: list[SessionWindow] = []

    if weekday == 5:  # Saturday
        return windows
    if weekday == 6:  # Sunday: 5PM -> midnight
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(17, 0), time(0, 0)
        )
        windows.append(SessionWindow("regular", start_utc, end_utc))
        return windows
    if weekday == 4:  # Friday: midnight -> 5PM
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(0, 0), time(17, 0)
        )
        windows.append(SessionWindow("regular", start_utc, end_utc))
        return windows

    # Mon-Thu with daily maintenance 5-6PM ET
    start_utc, end_utc = _local_window_to_utc(target_date, et, time(0, 0), time(17, 0))
    windows.append(SessionWindow("regular", start_utc, end_utc))
    start_utc, end_utc = _local_window_to_utc(target_date, et, time(18, 0), time(0, 0))
    windows.append(SessionWindow("regular", start_utc, end_utc))
    return windows


def _sessions_for_rates(target_date: date) -> list[SessionWindow]:
    et = ZoneInfo("America/New_York")
    if _weekday(target_date) > 4:
        return []
    start_utc, end_utc = _local_window_to_utc(target_date, et, time(8, 0), time(17, 0))
    return [SessionWindow("regular", start_utc, end_utc)]


def _sessions_24x7(target_date: date) -> list[SessionWindow]:
    start_utc = datetime.combine(target_date, time(0, 0), tzinfo=ZoneInfo("UTC"))
    end_utc = start_utc + timedelta(days=1)
    return [SessionWindow("regular", start_utc, end_utc)]


def _sessions_for_commodity(target_date: date) -> list[SessionWindow]:
    et = ZoneInfo("America/New_York")
    weekday = _weekday(target_date)
    windows: list[SessionWindow] = []

    if weekday == 5:  # Saturday
        return windows
    if weekday == 6:  # Sunday: 6PM -> midnight
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(18, 0), time(0, 0)
        )
        windows.append(SessionWindow("regular", start_utc, end_utc))
        return windows
    if weekday == 4:  # Friday: midnight -> 5PM
        start_utc, end_utc = _local_window_to_utc(
            target_date, et, time(0, 0), time(17, 0)
        )
        windows.append(SessionWindow("regular", start_utc, end_utc))
        return windows

    # Mon-Thu with daily maintenance 5-6PM ET
    start_utc, end_utc = _local_window_to_utc(target_date, et, time(0, 0), time(17, 0))
    windows.append(SessionWindow("regular", start_utc, end_utc))
    start_utc, end_utc = _local_window_to_utc(target_date, et, time(18, 0), time(0, 0))
    windows.append(SessionWindow("regular", start_utc, end_utc))
    return windows


def normalize_asset_class(asset_class: str) -> str:
    if not asset_class:
        return ""
    asset_class = asset_class.lower()
    aliases = {
        "metals": "metals",
        "metal": "metals",
        "equity-us": "us-equities",
        "us-equities": "us-equities",
        "fx": "fx",
        "commodity": "commodity",
        "commodities": "commodity",
        "rates": "us-treasuries",
        "us-treasuries": "us-treasuries",
        "treasuries": "us-treasuries",
        "crypto": "crypto",
        "crypto-redemption-rate": "crypto",
        "funding-rate": "crypto",
        "reference-rates": "reference-rates",
    }
    return aliases.get(asset_class, asset_class)


def get_session_windows(asset_class: str, target_date: date) -> list[SessionWindow]:
    """
    Return UTC session windows for the asset class and date.

    Note: Holiday calendars are not applied in this low-risk implementation.
    """
    normalized = normalize_asset_class(asset_class)

    if normalized == "us-equities":
        return _sessions_for_us_equities(target_date)
    if normalized.startswith("equity-"):
        country = normalized.split("-", 1)[1]
        if country in {"fr", "nl", "ie"}:
            return _sessions_for_eu_equities(target_date, "Europe/Paris")
        if country == "de":
            return _sessions_for_eu_equities(target_date, "Europe/Berlin")
        if country == "gb":
            return _sessions_for_uk_equities(target_date)
        if country == "hk":
            return _sessions_for_asia_equities(
                target_date,
                "Asia/Hong_Kong",
                (time(9, 30), time(12, 0)),
                (time(13, 0), time(16, 0)),
            )
        if country == "cn":
            return _sessions_for_asia_equities(
                target_date,
                "Asia/Shanghai",
                (time(9, 30), time(11, 30)),
                (time(13, 0), time(14, 57)),
            )
        if country == "jp":
            return _sessions_for_asia_equities(
                target_date,
                "Asia/Tokyo",
                (time(9, 0), time(11, 30)),
                (time(12, 30), time(15, 30)),
            )
        return _sessions_for_eu_equities(target_date, "Europe/Paris")

    if normalized in {"fx", "emerging-fx", "emerging-markets-fx"}:
        return _sessions_for_fx(target_date)
    if normalized == "metals":
        return _sessions_for_metals(target_date)
    if normalized in {"us-treasuries"}:
        return _sessions_for_rates(target_date)
    if normalized in {"reference-rates"}:
        return _sessions_24x7(target_date)
    if normalized in {"crypto"}:
        return _sessions_24x7(target_date)
    if normalized in {"commodity"}:
        return _sessions_for_commodity(target_date)

    return []


def combine_session_windows(
    windows: Iterable[SessionWindow], session_name: str
) -> list[SessionWindow]:
    combined: list[SessionWindow] = []
    for window in windows:
        if window.session != session_name:
            continue
        combined.append(window)
    return combined
