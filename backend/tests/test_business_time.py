from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.business_time import CalendarSpec, add_business_minutes, business_minutes_between

IST = ZoneInfo("Asia/Kolkata")
CAL = CalendarSpec(tz="Asia/Kolkata", start=time(9, 30), end=time(18, 30), working_days="1111110",
                   holidays=frozenset({date(2026, 10, 2)}))


def ist(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_within_same_day():
    out = add_business_minutes(ist(2026, 10, 12, 10), 60, CAL)  # Monday
    assert out == ist(2026, 10, 12, 11).astimezone(timezone.utc)


def test_rolls_to_next_working_day():
    out = add_business_minutes(ist(2026, 10, 12, 18), 60, CAL)  # 30 min left Mon, 30 min Tue
    assert out.astimezone(IST) == ist(2026, 10, 13, 10)


def test_before_hours_starts_at_opening():
    assert add_business_minutes(ist(2026, 10, 12, 7), 30, CAL).astimezone(IST) == ist(2026, 10, 12, 10)


def test_skips_sunday():
    # Saturday 18:00 + 60 => 30 on Sat, Sunday off, 30 on Monday
    assert add_business_minutes(ist(2026, 10, 10, 18), 60, CAL).astimezone(IST) == ist(2026, 10, 12, 10)


def test_skips_holiday():
    # Thu 1 Oct 18:30 + 30 => Fri 2 Oct is a holiday => Sat 3 Oct 10:00
    assert add_business_minutes(ist(2026, 10, 1, 18, 30), 30, CAL).astimezone(IST) == ist(2026, 10, 3, 10)


def test_between_is_inverse_of_add():
    start = ist(2026, 10, 9, 15, 17)
    for minutes in (1, 59, 540, 1000, 2700):
        end = add_business_minutes(start, minutes, CAL)
        assert business_minutes_between(start, end, CAL) == minutes


def test_between_excludes_nights_and_weekend():
    assert business_minutes_between(ist(2026, 10, 10, 18), ist(2026, 10, 12, 10), CAL) == 60


def test_naive_datetimes_rejected():
    with pytest.raises(ValueError):
        add_business_minutes(datetime(2026, 1, 1, 10), 5, CAL)


def test_invalid_calendar_rejected():
    with pytest.raises(ValueError):
        CalendarSpec(working_days="0000000")
    with pytest.raises(ValueError):
        CalendarSpec(start=time(18), end=time(9))
