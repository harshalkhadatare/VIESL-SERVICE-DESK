"""Pure business-hours arithmetic. No database access — easy to unit test.

A calendar is defined by a timezone, a daily working window, working weekdays
and a set of holiday dates (local dates in the calendar's timezone).
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_MAX_DAYS = 3 * 366  # guard against misconfigured calendars with no working time


@dataclass(frozen=True)
class CalendarSpec:
    tz: str = "Asia/Kolkata"
    start: time = time(9, 30)
    end: time = time(18, 30)
    working_days: str = "1111100"  # Mon..Sun
    holidays: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self):
        if len(self.working_days) != 7 or set(self.working_days) - {"0", "1"}:
            raise ValueError("working_days must be 7 characters of 0/1")
        if self.end <= self.start:
            raise ValueError("work_end must be after work_start (overnight shifts not supported)")
        if "1" not in self.working_days:
            raise ValueError("calendar must have at least one working day")

    @classmethod
    def from_model(cls, cal) -> "CalendarSpec":
        return cls(tz=cal.timezone, start=cal.work_start, end=cal.work_end, working_days=cal.working_days,
                   holidays=frozenset(h.holiday_date for h in cal.holidays))

    def window(self, d: date) -> tuple[datetime, datetime] | None:
        if self.working_days[d.weekday()] != "1" or d in self.holidays:
            return None
        z = ZoneInfo(self.tz)
        return datetime.combine(d, self.start, z), datetime.combine(d, self.end, z)


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("timezone-aware datetime required")


def add_business_minutes(start: datetime, minutes: int, cal: CalendarSpec) -> datetime:
    """Return the UTC instant that is `minutes` business minutes after `start`."""
    _require_aware(start)
    if minutes < 0:
        raise ValueError("minutes must be >= 0")
    z = ZoneInfo(cal.tz)
    cur = start.astimezone(z)
    remaining = float(minutes)
    for _ in range(_MAX_DAYS):
        win = cal.window(cur.date())
        if win:
            ws, we = win
            if cur < ws:
                cur = ws
            if cur < we:
                avail = (we - cur).total_seconds() / 60
                if remaining <= avail:
                    return (cur + timedelta(minutes=remaining)).astimezone(timezone.utc)
                remaining -= avail
        cur = datetime.combine(cur.date() + timedelta(days=1), time(0), z)
    raise ValueError("Business calendar has no working time within the search horizon")


def business_minutes_between(a: datetime, b: datetime, cal: CalendarSpec) -> int:
    """Whole business minutes elapsed from a to b (0 if b <= a)."""
    _require_aware(a)
    _require_aware(b)
    if b <= a:
        return 0
    z = ZoneInfo(cal.tz)
    la, lb = a.astimezone(z), b.astimezone(z)
    total = 0.0
    d = la.date()
    while d <= lb.date():
        win = cal.window(d)
        if win:
            s, e = max(win[0], la), min(win[1], lb)
            if e > s:
                total += (e - s).total_seconds() / 60
        d += timedelta(days=1)
    return int(total)
