import datetime

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_day_spec(spec: str) -> set:
    spec = spec.strip()
    if spec == "*":
        return set(range(7))
    result = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                start_idx = _DAY_NAMES.index(a.strip())
                end_idx   = _DAY_NAMES.index(b.strip())
            except ValueError:
                raise ValueError(f"Unknown day name in schedule: {part!r}")
            if start_idx <= end_idx:
                result.update(range(start_idx, end_idx + 1))
            else:
                result.update(range(start_idx, 7))
                result.update(range(0, end_idx + 1))
        else:
            try:
                result.add(_DAY_NAMES.index(part))
            except ValueError:
                raise ValueError(f"Unknown day name in schedule: {part!r}")
    return result


def _parse_hhmm(s: str) -> datetime.time:
    try:
        h, m = s.strip().split(":")
        return datetime.time(int(h), int(m))
    except Exception:
        raise ValueError(f"Invalid time format (expected HH:MM): {s!r}")


def _time_in_window(t, start, end) -> bool:
    if start <= end:
        return start <= t < end
    return t >= start or t < end   # overnight window


def is_scheduled_now(schedule: list) -> bool:
    """Return True if the current time falls within any window in schedule.
    An empty schedule means always active."""
    if not schedule:
        return True
    now     = datetime.datetime.now()
    current = now.time().replace(second=0, microsecond=0)
    today   = now.weekday()   # 0=Mon … 6=Sun
    for entry in schedule:
        if len(entry) == 2:
            if _time_in_window(current, _parse_hhmm(entry[0]), _parse_hhmm(entry[1])):
                return True
        elif len(entry) == 3:
            if today not in _parse_day_spec(str(entry[0])):
                continue
            if _time_in_window(current, _parse_hhmm(entry[1]), _parse_hhmm(entry[2])):
                return True
    return False
