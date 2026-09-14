"""Working time — the clock every service-desk duration is measured on.

The complaint this module exists to answer is "my query was not handled". To
answer it you need to say how long a ticket sat, and at which step it sat. That
number is worthless if it is wall-clock: a query raised at 16:55 on Friday and
answered at 08:10 on Monday took 15 minutes of anyone's working life, and 63
hours on a wall clock. Report the wall clock and every Monday morning looks like
a breach, the team stops believing the figure, and the figure stops being used.

So durations are measured in **business seconds**: time inside the working
window, on working days, excluding public holidays.

Both measures are always available — the raw timestamps are stored on every
event, so wall-clock elapsed is a subtraction away and nothing is lost by
choosing one to report. What is NOT recoverable is a timestamp never taken,
which is why the model records one at every step.

The engine is deliberately pure: it takes a ``WorkWeek`` value, not a database
row, so it can be tested against awkward calendars (a holiday in the middle of a
ticket, a ticket raised at midnight, a ticket resolved before it started)
without fixtures.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# A ticket open for longer than this is not measured further. Without a cap a
# single row with a corrupt timestamp (a year 2099 resolved_at, say) would walk
# this loop three hundred thousand times on a page load.
MAX_DAYS_SPANNED = 3660  # ten years


@dataclass(frozen=True)
class WorkWeek:
    """When the desk is open.

    ``start_minute``/``end_minute`` are minutes from local midnight, so 8am–5pm
    is 480–1020. ``workdays`` uses Python's weekday numbering, Monday = 0.
    """

    start_minute: int = 8 * 60
    end_minute: int = 17 * 60
    workdays: frozenset = frozenset({0, 1, 2, 3, 4})
    holidays: frozenset = frozenset()
    tz: str = "Africa/Nairobi"

    @property
    def zone(self):
        try:
            return ZoneInfo(self.tz)
        except Exception:  # noqa: BLE001 — an unknown zone must not break a page
            return ZoneInfo("Africa/Nairobi")

    @property
    def seconds_per_day(self):
        return max(0, (self.end_minute - self.start_minute) * 60)

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.workdays and day not in self.holidays


def _local(moment: datetime, week: WorkWeek) -> datetime:
    """Same instant, expressed in the desk's own timezone.

    A naive datetime is assumed to already be local: the alternative is to guess
    UTC and silently shift every duration by three hours.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=week.zone)
    return moment.astimezone(week.zone)


def _window(day: date, week: WorkWeek):
    """(opens, closes) for a day, or None if the desk is shut."""
    if not week.is_working_day(day):
        return None
    midnight = datetime(day.year, day.month, day.day, tzinfo=week.zone)
    return (
        midnight + timedelta(minutes=week.start_minute),
        midnight + timedelta(minutes=week.end_minute),
    )


def business_seconds(start: datetime, end: datetime, week: WorkWeek = None) -> int:
    """Working seconds between two instants. Never negative.

    An end before the start returns 0 rather than a negative duration: it means
    the timestamps are out of order, and a negative age rendered on a dashboard
    is a puzzle, where zero is merely wrong in a way somebody will report.
    """
    week = week or WorkWeek()
    if start is None or end is None:
        return 0
    start, end = _local(start, week), _local(end, week)
    if end <= start:
        return 0
    if week.seconds_per_day <= 0:
        return 0

    total = 0
    day = start.date()
    last = end.date()
    spanned = 0
    while day <= last:
        spanned += 1
        if spanned > MAX_DAYS_SPANNED:
            break
        window = _window(day, week)
        if window is not None:
            opens, closes = window
            # The overlap of [start, end] with this day's window.
            lo = max(opens, start)
            hi = min(closes, end)
            if hi > lo:
                total += int((hi - lo).total_seconds())
        day += timedelta(days=1)
    return total


def add_business_seconds(start: datetime, seconds: int, week: WorkWeek = None) -> datetime:
    """When a deadline of ``seconds`` working time from ``start`` falls due.

    This is what turns "respond within 4 working hours" into a timestamp the
    dashboard can compare against now, and the reason a ticket raised late on
    Friday is not overdue on Saturday morning.
    """
    week = week or WorkWeek()
    if seconds is None or seconds <= 0 or week.seconds_per_day <= 0:
        return _local(start, week)

    moment = _local(start, week)
    remaining = int(seconds)
    day = moment.date()
    spanned = 0

    while remaining > 0:
        spanned += 1
        if spanned > MAX_DAYS_SPANNED:
            # Out of road. Returning the last moment considered is a visibly
            # wrong date, which is better than looping until the worker dies.
            return moment
        window = _window(day, week)
        if window is not None:
            opens, closes = window
            cursor = max(opens, moment) if day == moment.date() else opens
            if cursor < closes:
                available = int((closes - cursor).total_seconds())
                if available >= remaining:
                    return cursor + timedelta(seconds=remaining)
                remaining -= available
        day += timedelta(days=1)
    return moment


def describe(seconds) -> str:
    """A duration a person can read: "2d 3h", "45m", "—".

    Days here are WORKING days of the desk's own length, not 24 hours — showing
    "3d" for a nine-hour working window and meaning 72 hours would misreport the
    thing this module exists to report.
    """
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    per_day = max(1, WorkWeek().seconds_per_day // 3600)
    hours = minutes // 60
    minutes = minutes % 60
    if hours < per_day:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days = hours // per_day
    hours = hours % per_day
    return f"{days}d {hours}h" if hours else f"{days}d"
