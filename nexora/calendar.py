"""Wall-clock recurrence. Gaps are skipped; folds run once at the first occurrence."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def next_run(spec, after):
    zone = ZoneInfo(spec['zone'])
    hour, minute = map(int, spec['time'].split(':'))
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError('Use HH:MM')
    days = spec.get('days', list(range(7)))
    if not days or any(type(d) is not int or d not in range(7) for d in days):
        raise ValueError('Weekdays must be 0 (Monday) through 6 (Sunday)')
    start = datetime.fromtimestamp(after, zone).date()
    for offset in range(370):
        date = start + timedelta(days=offset)
        if date.weekday() not in days:
            continue
        local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone, fold=0)
        stamp = local.timestamp()
        # Roundtrip detects nonexistent local times. fold=0 deduplicates a fall-back hour.
        if datetime.fromtimestamp(stamp, zone).replace(tzinfo=None) != local.replace(tzinfo=None):
            continue
        if stamp > after:
            return stamp
    raise ValueError('No valid recurrence within a year')


def local_label(stamp, zone):
    return datetime.fromtimestamp(stamp, ZoneInfo(zone)).isoformat(timespec='minutes')
