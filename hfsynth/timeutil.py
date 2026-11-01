"""Time helpers: US daylight-saving rules without needing the tzdata package.

Every transaction stores a UTC timestamp, the UTC offset in force and the *local*
calendar date. That is what makes the timezone-boundary edge case (E4) checkable:
a purchase made on the last local evening of a month lands in the next UTC month.
"""
import calendar
import datetime as dt
from functools import lru_cache


def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    shift = (6 - d.weekday()) % 7
    return d + dt.timedelta(days=shift + 7 * (n - 1))


@lru_cache(maxsize=None)
def dst_bounds(year):
    """(start, end) local-naive datetimes. DST starts 2nd Sunday of March 02:00
    and ends 1st Sunday of November 02:00 (US rules)."""
    s = _nth_sunday(year, 3, 2)
    e = _nth_sunday(year, 11, 1)
    return dt.datetime(s.year, s.month, s.day, 2), dt.datetime(e.year, e.month, e.day, 2)


def local_to_utc(local, std_off_min):
    """Return (utc_naive, offset_minutes_in_force, local_possibly_adjusted)."""
    start, end = dst_bounds(local.year)
    if start <= local < start + dt.timedelta(hours=1):  # non-existent hour
        local = local + dt.timedelta(hours=1)
    off = std_off_min + 60 if start <= local < end else std_off_min
    return local - dt.timedelta(minutes=off), off, local


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def last_day(year, month):
    return dt.date(year, month, days_in_month(year, month))


def iso_utc(utc):
    return utc.isoformat() + "Z"
