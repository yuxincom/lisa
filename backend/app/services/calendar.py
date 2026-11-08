"""工作日历引擎。

班次、周休息日、法定节假日与调休上班日全部由 settings.calendar 驱动，
不再硬编码 8:00-20:00 / 周日休。排程与校验必须通过这里的函数换算工作时间，
否则交期承诺会偏乐观。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator

MINUTES_PER_DAY = 1440


class CalendarConfigError(ValueError):
    """日历配置非法：班次时间错误、班次重叠等。"""


class CalendarHorizonError(RuntimeError):
    """在 horizon_days 跨度内找不到足够的工作时段，通常意味着停产窗口过长。"""


def _to_minutes(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise CalendarConfigError(f"{field}: 布尔值不是合法时间")
    if isinstance(value, time):
        minutes = value.hour * 60 + value.minute
    elif isinstance(value, (int, float)):
        minutes = int(round(float(value) * 60))
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) < 2:
            raise CalendarConfigError(f"{field}: 时间需写成 HH:MM，收到 {value!r}")
        try:
            hours, minute = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise CalendarConfigError(f"{field}: 时间无法解析 {value!r}") from exc
        minutes = hours * 60 + minute
    else:
        raise CalendarConfigError(f"{field}: 不支持的时间类型 {type(value).__name__}")
    if not 0 <= minutes <= MINUTES_PER_DAY:
        raise CalendarConfigError(f"{field}: {value!r} 超出 00:00-24:00")
    return minutes


def _to_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise CalendarConfigError(f"{field}: 日期需写成 YYYY-MM-DD，收到 {value!r}") from exc
    raise CalendarConfigError(f"{field}: 不支持的日期类型 {type(value).__name__}")


@dataclass(frozen=True)
class Shift:
    name: str
    start: int
    end: int

    @property
    def overnight(self) -> bool:
        return self.end <= self.start

    @property
    def duration_minutes(self) -> int:
        return (self.end - self.start) % MINUTES_PER_DAY or MINUTES_PER_DAY

    def windows(self, day: date) -> tuple[tuple[datetime, datetime], ...]:
        midnight = datetime.combine(day, time(0, 0))
        start = midnight + timedelta(minutes=self.start)
        if not self.overnight:
            return ((start, midnight + timedelta(minutes=self.end)),)
        return ((start, midnight + timedelta(days=1, minutes=self.end)),)


DEFAULT_CALENDAR_CONFIG: dict[str, Any] = {
    "shifts": [{"name": "白班", "start": "08:00", "end": "20:00"}],
    "workdays": [0, 1, 2, 3, 4, 5],
    "holidays": [],
    "workday_overrides": [],
    "horizon_days": 400,
}


class WorkCalendar:
    def __init__(
        self,
        shifts: list[Shift],
        workdays: list[int],
        holidays: set[date],
        workday_overrides: set[date],
        horizon_days: int = 400,
    ) -> None:
        if not shifts:
            raise CalendarConfigError("calendar.shifts 至少需要一个班次")
        for shift in shifts:
            if not 0 <= shift.start < MINUTES_PER_DAY:
                raise CalendarConfigError(f"班次 {shift.name} 起始时刻非法")
            if shift.start == shift.end:
                raise CalendarConfigError(f"班次 {shift.name} 起止时刻相同")
        ordered = sorted(shifts, key=lambda s: s.start)
        for current, nxt in zip(ordered, ordered[1:]):
            if current.overnight and nxt.start < current.end % MINUTES_PER_DAY:
                raise CalendarConfigError(
                    f"班次 {current.name}（跨零点）与 {nxt.name} 时间重叠"
                )
        for first, second in zip(ordered, ordered[1:]):
            if not first.overnight and second.start < first.end:
                raise CalendarConfigError(f"班次 {first.name} 与 {second.name} 时间重叠")
        bad = [d for d in workdays if not 0 <= int(d) <= 6]
        if bad:
            raise CalendarConfigError(f"workdays 取值必须在 0-6（周一=0），收到 {bad}")
        self.shifts = ordered
        self.workdays = {int(d) for d in workdays}
        self.holidays = set(holidays)
        self.workday_overrides = set(workday_overrides)
        self.horizon_days = max(1, int(horizon_days))
        self._window_cache: dict[date, list[tuple[datetime, datetime]]] = {}
        self._capacity_cache: dict[date, float] = {}

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "WorkCalendar":
        cfg = {**DEFAULT_CALENDAR_CONFIG, **(config or {})}
        shifts = [
            Shift(
                name=str(item.get("name") or f"班次{i + 1}"),
                start=_to_minutes(item.get("start", 8), f"shifts[{i}].start"),
                end=_to_minutes(item.get("end", 20), f"shifts[{i}].end"),
            )
            for i, item in enumerate(cfg["shifts"])
        ]
        return cls(
            shifts=shifts,
            workdays=list(cfg["workdays"]),
            holidays={_to_date(d, "holidays") for d in cfg.get("holidays") or []},
            workday_overrides={_to_date(d, "workday_overrides") for d in cfg.get("workday_overrides") or []},
            horizon_days=int(cfg.get("horizon_days", 400)),
        )

    def is_production_day(self, day: date) -> bool:
        if day in self.workday_overrides:
            return True
        if day in self.holidays:
            return False
        return day.weekday() in self.workdays

    def windows_starting_on(self, day: date) -> list[tuple[datetime, datetime]]:
        cached = self._window_cache.get(day)
        if cached is not None:
            return cached
        windows: list[tuple[datetime, datetime]] = []
        if self.is_production_day(day):
            for shift in self.shifts:
                windows.extend(shift.windows(day))
        windows.sort()
        self._window_cache[day] = windows
        return windows

    def iter_windows(self, after: datetime, until: datetime | None = None) -> Iterator[tuple[datetime, datetime]]:
        day = (after - timedelta(days=1)).date()
        limit = (until if until and until > after else after + timedelta(days=self.horizon_days)).date()
        while day <= limit:
            for window in self.windows_starting_on(day):
                if window[1] > after and (until is None or window[0] < until):
                    yield window
            day += timedelta(days=1)

    def align(self, moment: datetime) -> datetime:
        # 只能向后取整：向前截断秒会让后继工序早于前序完工（HC-12）或让相邻机位重叠（HC-09）。
        if moment.second or moment.microsecond:
            moment = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        else:
            moment = moment.replace(microsecond=0)
        for start, end in self.iter_windows(moment):
            if moment < start:
                return start
            if moment < end:
                return moment
        raise CalendarHorizonError(
            f"{moment:%Y-%m-%d %H:%M} 之后 {self.horizon_days} 天内没有可用工作时段，请检查日历配置"
        )

    def add_minutes(self, start: datetime, minutes: float) -> datetime:
        cursor = self.align(start)
        remaining = max(float(minutes), 0.0)
        if remaining == 0:
            return cursor
        for window_start, window_end in self.iter_windows(cursor):
            seg_start = max(cursor, window_start)
            if seg_start >= window_end:
                continue
            available = (window_end - seg_start).total_seconds() / 60.0
            if remaining <= available:
                return seg_start + timedelta(minutes=remaining)
            remaining -= available
        raise CalendarHorizonError(
            f"从 {start:%Y-%m-%d %H:%M} 起 {self.horizon_days} 天内工时不足，请检查停产窗口"
        )

    def minutes_between(self, start: datetime, end: datetime) -> float:
        if end <= start:
            return 0.0
        total = 0.0
        for window_start, window_end in self.iter_windows(start, end):
            seg_start = max(start, window_start)
            seg_end = min(end, window_end)
            if seg_end > seg_start:
                total += (seg_end - seg_start).total_seconds() / 60.0
        return total

    def day_capacity_minutes(self, day: date) -> float:
        cached = self._capacity_cache.get(day)
        if cached is not None:
            return cached
        start = datetime.combine(day, time(0, 0))
        value = self.minutes_between(start, start + timedelta(days=1))
        self._capacity_cache[day] = value
        return value

    def contains(self, moment: datetime) -> bool:
        return any(start <= moment < end for start, end in self.iter_windows(moment, moment + timedelta(minutes=1)))

    def to_config(self) -> dict[str, Any]:
        return {
            "shifts": [
                {"name": s.name, "start": f"{s.start // 60:02d}:{s.start % 60:02d}",
                 "end": f"{s.end // 60:02d}:{s.end % 60:02d}" if s.end != MINUTES_PER_DAY else "24:00"}
                for s in self.shifts
            ],
            "workdays": sorted(self.workdays),
            "holidays": sorted(d.isoformat() for d in self.holidays),
            "workday_overrides": sorted(d.isoformat() for d in self.workday_overrides),
            "horizon_days": self.horizon_days,
        }


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """把 settings 里的 calendar / 旧版 shift 合并成统一日历配置。"""
    raw = raw or {}
    config = dict(raw.get("calendar") or {})
    if "shifts" not in config:
        legacy = raw.get("shift") or {}
        start = legacy.get("start", 8)
        end = legacy.get("end", 20)
        days = int(legacy.get("days", 6))
        config["shifts"] = [{"name": "白班", "start": start, "end": end}]
        config["workdays"] = list(range(max(1, min(7, days))))
    return {**DEFAULT_CALENDAR_CONFIG, **config}


_ACTIVE = WorkCalendar.from_config(DEFAULT_CALENDAR_CONFIG)


def configure_calendar(settings: dict[str, Any] | None) -> WorkCalendar:
    """用整份 settings（含 calendar 或旧版 shift）刷新进程内生效的日历。"""
    global _ACTIVE
    _ACTIVE = WorkCalendar.from_config(normalize_config(settings))
    return _ACTIVE


def apply_calendar_config(config: dict[str, Any] | None) -> WorkCalendar:
    """直接用日历块刷新，供 /api/system/calendar 校验后立即生效。"""
    global _ACTIVE
    _ACTIVE = WorkCalendar.from_config({**DEFAULT_CALENDAR_CONFIG, **(config or {})})
    return _ACTIVE


def validate_calendar_config(config: dict[str, Any] | None) -> WorkCalendar:
    """构造但不生效，用于落库前校验。非法配置抛 CalendarConfigError。"""
    return WorkCalendar.from_config({**DEFAULT_CALENDAR_CONFIG, **(config or {})})


def active_calendar() -> WorkCalendar:
    return _ACTIVE


def is_workday(moment: datetime) -> bool:
    return _ACTIVE.is_production_day(moment.date())


def align_to_work(moment: datetime) -> datetime:
    return _ACTIVE.align(moment)


def add_work_minutes(start: datetime, minutes: float) -> datetime:
    return _ACTIVE.add_minutes(start, minutes)


def work_minutes_between(start: datetime, end: datetime) -> float:
    return _ACTIVE.minutes_between(start, end)


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
