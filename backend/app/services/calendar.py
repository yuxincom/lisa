from __future__ import annotations

from datetime import datetime, time, timedelta

WORK_START = time(8, 0)
WORK_END = time(20, 0)
WORKDAY_HOURS = (WORK_END.hour - WORK_START.hour)


def is_workday(dt: datetime) -> bool:
    return dt.weekday() != 6


def align_to_work(dt: datetime) -> datetime:
    """Move a timestamp forward to the next valid shift start."""
    dt = dt.replace(second=0, microsecond=0)
    while True:
        if not is_workday(dt):
            dt = (dt + timedelta(days=1)).replace(hour=WORK_START.hour, minute=0)
            continue
        if dt.time() < WORK_START:
            return dt.replace(hour=WORK_START.hour, minute=0)
        if dt.time() >= WORK_END:
            dt = (dt + timedelta(days=1)).replace(hour=WORK_START.hour, minute=0)
            continue
        return dt


def add_work_minutes(start: datetime, minutes: float) -> datetime:
    """Advance by working minutes, skipping nights and Sundays."""
    cursor = align_to_work(start)
    remaining = max(float(minutes), 0.0)
    guard = 0
    while remaining > 0 and guard < 500:
        guard += 1
        end_of_shift = cursor.replace(hour=WORK_END.hour, minute=0)
        available = max((end_of_shift - cursor).total_seconds() / 60.0, 0.0)
        if remaining <= available:
            return cursor + timedelta(minutes=remaining)
        remaining -= available
        cursor = align_to_work((cursor + timedelta(days=1)).replace(hour=WORK_START.hour, minute=0))
    return cursor


def work_minutes_between(start: datetime, end: datetime) -> float:
    if end <= start:
        return 0.0
    total = 0.0
    cursor = start
    guard = 0
    while cursor < end and guard < 500:
        guard += 1
        if is_workday(cursor):
            day_start = cursor.replace(hour=WORK_START.hour, minute=0, second=0)
            day_end = cursor.replace(hour=WORK_END.hour, minute=0, second=0)
            seg_start = max(cursor, day_start)
            seg_end = min(end, day_end)
            if seg_end > seg_start:
                total += (seg_end - seg_start).total_seconds() / 60.0
        cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0)
    return total


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
