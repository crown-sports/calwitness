"""Private worker: one calendar, one fresh timezone cache, bounded expansion."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, reset_tzpath

from .compare import MAX_BYTES, MAX_EVENTS, MAX_WORK, issue


class Unsupported(ValueError):
    def __init__(self, code: str, message: str, location: str = "VCALENDAR"):
        self.code, self.message, self.location = code, message, location


def fail(code: str, message: str, location: str = "VCALENDAR") -> None:
    raise Unsupported(code, message, location)


def _raw_preflight(data: bytes) -> dict:
    """Check rules before Calendar.from_ical can expand embedded VTIMEZONEs."""
    if len(data) > MAX_BYTES:
        fail("INPUT_LIMIT", "Input exceeds the 4 MiB limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        fail("INPUT_ENCODING", "Only UTF-8 iCalendar input is supported.")
    if "\x00" in text:
        fail("PARSE_ERROR", "Input contains a NUL character.")
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    if len(lines) > 50_000 or any(len(line) > 65_536 for line in lines):
        fail("INPUT_LIMIT", "Input exceeds the line-count or unfolded-line limit.")
    stack = []
    timezone_count = 0
    observance_count = 0
    event_index = -1
    durations = {}
    for line in lines:
        name, sep, value = line.partition(":")
        header = name.upper()
        name = name.split(";", 1)[0].upper()
        if not sep:
            if line.strip():
                fail("PARSE_ERROR", "A content line has no value separator.")
            continue
        if name in ("DTSTART", "DTEND", "RECURRENCE-ID", "EXDATE", "RDATE"):
            if ";TZID=" in header and any(v.endswith("Z") for v in value.upper().split(",")):
                fail("INVALID_DATE", "A UTC DATE-TIME cannot also specify TZID.")
        if name == "BEGIN":
            stack.append(value.upper())
            if len(stack) > 8:
                fail("INPUT_LIMIT", "Component nesting exceeds the limit.")
            if value.upper() == "VTIMEZONE":
                timezone_count += 1
                observance_count = 0
                if timezone_count > 32:
                    fail("INPUT_LIMIT", "There are more than 32 embedded timezones.")
            elif "VTIMEZONE" in stack and value.upper() in ("STANDARD", "DAYLIGHT"):
                observance_count += 1
                if observance_count > 16:
                    fail("INPUT_LIMIT", "An embedded timezone has more than 16 observances.")
            elif value.upper() == "VEVENT":
                event_index += 1
                if stack != ["VCALENDAR", "VEVENT"]:
                    fail("UNSUPPORTED_COMPONENT", "VEVENT must be a direct child of VCALENDAR.")
        elif name == "END":
            if not stack or stack.pop() != value.upper():
                fail("PARSE_ERROR", "Component boundaries are not balanced.")
        elif name in ("RRULE", "EXRULE"):
            if name == "EXRULE":
                fail("UNSUPPORTED_RULE", "EXRULE is not supported; use explicit EXDATE values.")
            parts = {}
            for part in value.upper().split(";"):
                key, equals, val = part.partition("=")
                if not equals or key in parts or not val:
                    fail("INVALID_RULE", "A recurrence rule contains invalid or duplicate parts.")
                parts[key] = val
            if parts.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
                fail(
                    "UNSUPPORTED_RULE",
                    "Only DAILY, WEEKLY, MONTHLY and YEARLY rules are supported.",
                )
            allowed = {
                "FREQ",
                "UNTIL",
                "COUNT",
                "INTERVAL",
                "BYSECOND",
                "BYMINUTE",
                "BYHOUR",
                "BYDAY",
                "BYMONTHDAY",
                "BYYEARDAY",
                "BYWEEKNO",
                "BYMONTH",
                "BYSETPOS",
                "WKST",
            }
            if parts.keys() - allowed:
                fail("UNSUPPORTED_RULE", "A recurrence rule uses an unsupported extension.")
            if "COUNT" in parts and "UNTIL" in parts:
                fail("INVALID_RULE", "COUNT and UNTIL cannot appear in the same rule.")
            weekdays = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
            if "WKST" in parts and parts["WKST"] not in weekdays:
                fail("INVALID_RULE", "WKST must name a weekday.")
            for key, maximum, signed in (
                ("BYMONTHDAY", 31, True),
                ("BYYEARDAY", 366, True),
                ("BYWEEKNO", 53, True),
                ("BYMONTH", 12, False),
                ("BYSETPOS", 366, True),
            ):
                for number in parts.get(key, "").split(",") if key in parts else []:
                    if not re.fullmatch(r"[+-]?[0-9]+", number):
                        fail("INVALID_RULE", "A recurrence selector must contain integers.")
                    integer = int(number)
                    if integer == 0 or not (-maximum if signed else 1) <= integer <= maximum:
                        fail(
                            "INVALID_RULE", "A recurrence selector is outside its RFC 5545 range."
                        )
            if "BYDAY" in parts:
                for day in parts["BYDAY"].split(","):
                    match = re.fullmatch(r"([+-]?[0-9]+)?(MO|TU|WE|TH|FR|SA|SU)", day)
                    if not match:
                        fail("INVALID_RULE", "BYDAY contains an invalid weekday.")
                    if match.group(1) is not None:
                        number = int(match.group(1))
                        if number == 0 or not -53 <= number <= 53:
                            fail("INVALID_RULE", "A BYDAY ordinal is outside its RFC 5545 range.")
                        if parts["FREQ"] not in ("MONTHLY", "YEARLY") or "BYWEEKNO" in parts:
                            fail("INVALID_RULE", "Ordinal BYDAY is incompatible with this rule.")
            if (
                ("BYMONTHDAY" in parts and parts["FREQ"] == "WEEKLY")
                or ("BYYEARDAY" in parts and parts["FREQ"] != "YEARLY")
                or ("BYWEEKNO" in parts and parts["FREQ"] != "YEARLY")
            ):
                fail("INVALID_RULE", "A recurrence selector is incompatible with its frequency.")
            if "BYSETPOS" in parts and not any(
                k.startswith("BY") and k != "BYSETPOS" for k in parts
            ):
                fail("INVALID_RULE", "BYSETPOS requires another BY selector.")
            for key in ("COUNT", "INTERVAL"):
                if key in parts and (
                    not parts[key].isdigit() or not 1 <= int(parts[key]) <= 1_000_000
                ):
                    fail("INVALID_RULE", "COUNT or INTERVAL is outside the supported range.")
            slots = 1
            for key, maximum in (("BYSECOND", 59), ("BYMINUTE", 59), ("BYHOUR", 23)):
                if key in parts:
                    values = parts[key].split(",")
                    if any(not v.isdigit() or not 0 <= int(v) <= maximum for v in values):
                        fail("INVALID_RULE", "A recurrence time part is outside its valid range.")
                    slots *= len(values)
            if slots > 64:
                fail("EXPANSION_LIMIT", "A rule exceeds 64 candidate times per day.")
            if "VTIMEZONE" in stack and (
                parts["FREQ"] != "YEARLY"
                or any(k in parts for k in ("BYSECOND", "BYMINUTE", "BYHOUR"))
            ):
                fail(
                    "UNSUPPORTED_TIMEZONE",
                    "Embedded timezone rules must be YEARLY without time expansion.",
                )
        elif name == "DTSTART" and "VTIMEZONE" in stack:
            if not value[:4].isdigit() or not 1600 <= int(value[:4]) <= 2100:
                fail(
                    "UNSUPPORTED_TIMEZONE",
                    "Timezone observance starts must be within years 1600..2100.",
                )
        elif name == "DURATION" and stack and stack[-1] == "VEVENT":
            match = re.fullmatch(
                r"\+?P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?)", value
            )
            if not match or not any(match.groups()):
                fail("INVALID_EVENT", "Event DURATION must be a nonnegative RFC 5545 duration.")
            weeks, days, hours, minutes, seconds = (int(v or 0) for v in match.groups())
            durations[event_index] = (weeks * 7 + days, hours * 3600 + minutes * 60 + seconds)
    if stack:
        fail("PARSE_ERROR", "Component boundaries are not balanced.")
    return durations


def _iso(value: date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            fail("FLOATING_TIME", "A floating time needs --floating-zone.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def _kind(value: date | datetime) -> str:
    return "instant" if isinstance(value, datetime) else "date"


def _values(component, name):
    value = component.get(name)
    return value if isinstance(value, list) else [] if value is None else [value]


def _normalize(prop, embedded: dict, floating, location: str):
    value = prop.dt
    if not isinstance(value, (date, datetime)):
        fail(
            "UNSUPPORTED_DATE",
            "PERIOD and non-date recurrence values are not supported.",
            location,
        )
    tzid = prop.params.get("TZID")
    if not isinstance(value, datetime):
        if tzid:
            fail("INVALID_DATE", "A DATE value cannot have a TZID parameter.", location)
        return value
    if tzid:
        zone = embedded.get(str(tzid))
        if zone is None:
            try:
                zone = ZoneInfo(str(tzid))
            except (ZoneInfoNotFoundError, ValueError):
                fail(
                    "UNKNOWN_TIMEZONE",
                    "A TZID has neither an embedded definition nor an exact IANA match.",
                    location,
                )
        value = value.replace(tzinfo=zone)
    elif value.tzinfo is None:
        if floating is None:
            fail(
                "FLOATING_TIME",
                "A floating time needs --floating-zone; no calendar or machine zone is guessed.",
                location,
            )
        value = value.replace(tzinfo=floating)
    # A single ambiguous/nonexistent explicit time needs an interpretation policy,
    # which this release deliberately does not guess.
    from dateutil.tz import datetime_ambiguous, datetime_exists

    if not datetime_exists(value) or datetime_ambiguous(value):
        fail(
            "AMBIGUOUS_LOCAL_TIME",
            "An explicit local time is ambiguous or nonexistent at a clock change.",
            location,
        )
    prop.dt = value
    return value


def _timing(event, start, location, raw_duration):
    if "DTEND" in event and "DURATION" in event:
        fail("INVALID_EVENT", "DTEND and DURATION cannot both be present.", location)
    if "DTEND" in event:
        end = event["DTEND"].dt
        if _kind(start) != _kind(end) or _iso(end) < _iso(start):
            fail(
                "INVALID_EVENT",
                "Start and end must have the same type and nonnegative duration.",
                location,
            )
        if isinstance(start, datetime):
            return (
                0,
                (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds(),
            )
        return ((end - start).days, 0)
    elif "DURATION" in event:
        if raw_duration is None:
            fail("INVALID_EVENT", "Duration syntax could not be preserved.", location)
        if not isinstance(start, datetime) and raw_duration[1]:
            fail("INVALID_EVENT", "An all-day duration must contain whole days.", location)
        return raw_duration
    return (0, 0) if isinstance(start, datetime) else (1, 0)


def _effective_end(start, timing):
    days, seconds = timing
    end = start + timedelta(days=days)
    if isinstance(end, datetime):
        if days:
            from dateutil.tz import datetime_ambiguous, datetime_exists

            if not datetime_exists(end) or datetime_ambiguous(end):
                fail(
                    "AMBIGUOUS_LOCAL_TIME",
                    "A nominal-day duration ends at an ambiguous or nonexistent local time.",
                )
        end = end.astimezone(timezone.utc) + timedelta(seconds=seconds)
    return end


def _preflight_calendar(calendar, config: dict, raw_durations: dict) -> tuple[dict, dict, dict]:
    from icalendar import Calendar

    if not isinstance(calendar, Calendar) or calendar.name != "VCALENDAR":
        fail("PARSE_ERROR", "Input must contain exactly one VCALENDAR.")
    if calendar.errors:
        fail("PARSE_ERROR", "Calendar properties could not be parsed.")
    if calendar.get("VERSION") != "2.0":
        fail("UNSUPPORTED_VERSION", "Calendar VERSION must be exactly 2.0.")
    if calendar.get("METHOD") not in (None, "PUBLISH"):
        fail("UNSUPPORTED_METHOD", "Scheduling messages are not calendar snapshots.")
    if any(c.name not in ("VEVENT", "VTIMEZONE") for c in calendar.subcomponents):
        fail(
            "UNSUPPORTED_COMPONENT",
            "Only VEVENT and VTIMEZONE top-level components are supported.",
        )
    # X-WR-TIMEZONE is not authority for floating times in this tool.
    calendar.pop("X-WR-TIMEZONE", None)
    embedded = {}
    zones = calendar.walk("VTIMEZONE")
    if len(zones) > 32:
        fail("INPUT_LIMIT", "There are more than 32 embedded timezones.")
    for tz in zones:
        name = str(tz.get("TZID", ""))
        if not name or name in embedded or len(tz.subcomponents) > 16:
            fail("AMBIGUOUS_TIMEZONE", "Embedded timezone identifiers must be unique and bounded.")
        # Public conversion explicitly honors the file's rules, even for IANA IDs.
        embedded[name] = tz.to_tz(lookup_tzid=False)
    floating = None
    if config["floating_zone"]:
        try:
            floating = ZoneInfo(config["floating_zone"])
        except (ZoneInfoNotFoundError, ValueError):
            fail("UNKNOWN_TIMEZONE", "The requested floating timezone is not an exact IANA name.")
    events = calendar.walk("VEVENT")
    if len(events) > MAX_EVENTS:
        fail("INPUT_LIMIT", "There are more than 1000 event components.")
    groups = defaultdict(list)
    locations = {}
    timings = {}
    work = 0
    output_bound = 0
    last = date.fromisoformat(config["end"])
    focus = defaultdict(list)
    for item in config.get("focus", []):
        focus[item["series"]].append(date.fromisoformat(item["key"][:10]))
    for index, event in enumerate(events):
        loc = f"VEVENT[{index}]"
        locations[id(event)] = loc
        if event.errors:
            fail("PARSE_ERROR", "An event property could not be parsed.", loc)
        for field in ("UID", "DTSTART", "DTEND", "DURATION", "RECURRENCE-ID", "RRULE", "STATUS"):
            if len(_values(event, field)) > 1:
                fail(
                    "DUPLICATE_PROPERTY",
                    "An event repeats a singleton timing or identity property.",
                    loc,
                )
        uid = event.get("UID")
        if uid is None or not str(uid).strip():
            fail("MISSING_UID", "An event has no usable UID; identity is not guessed.", loc)
        if "DTSTART" not in event:
            fail("MISSING_START", "An event has no DTSTART.", loc)
        if "RECURRENCE-ID" in event and event["RECURRENCE-ID"].params.get("RANGE"):
            fail("UNSUPPORTED_RANGE", "RECURRENCE-ID RANGE is not supported.", loc)
        original_start = event["DTSTART"].dt
        was_floating = (
            isinstance(original_start, datetime)
            and original_start.tzinfo is None
            and not event["DTSTART"].params.get("TZID")
        )
        for name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
            if name in event:
                _normalize(event[name], embedded, floating, loc)
        start = event["DTSTART"].dt
        timings[id(event)] = _timing(event, start, loc, raw_durations.get(index))
        _effective_end(start, timings[id(event)])
        dates_count = 0
        for name in ("EXDATE", "RDATE"):
            for dates in _values(event, name):
                for prop in dates.dts:
                    # vDDDLists keeps TZID on the container in some parser versions.
                    if "TZID" in dates.params:
                        prop.params["TZID"] = dates.params["TZID"]
                    value = _normalize(prop, embedded, floating, loc)
                    if _kind(value) != _kind(start):
                        fail(
                            "DATE_TYPE_MISMATCH",
                            "Recurrence dates must match the DTSTART value type.",
                            loc,
                        )
                    dates_count += 1
        if dates_count > config["max_occurrences"]:
            fail("EXPANSION_LIMIT", "Explicit recurrence dates exceed the occurrence limit.", loc)
        if "RECURRENCE-ID" in event and _kind(event["RECURRENCE-ID"].dt) != _kind(start):
            fail("DATE_TYPE_MISMATCH", "RECURRENCE-ID must match the DTSTART value type.", loc)
        rule = event.get("RRULE")
        bound = 1 + dates_count
        if rule:
            if "RECURRENCE-ID" in event:
                fail(
                    "UNSUPPORTED_RULE",
                    "A detached override cannot define another recurrence rule.",
                    loc,
                )
            if not isinstance(start, datetime) and any(
                k in rule for k in ("BYHOUR", "BYMINUTE", "BYSECOND")
            ):
                fail("INVALID_RULE", "A DATE recurrence cannot expand time-of-day selectors.", loc)
            if "UNTIL" in rule:
                until = rule["UNTIL"][0]
                if _kind(until) != _kind(start):
                    fail("INVALID_RULE", "UNTIL must have the same value type as DTSTART.", loc)
                if isinstance(until, datetime):
                    if was_floating and until.tzinfo is None:
                        until = until.replace(tzinfo=floating).astimezone(timezone.utc)
                        rule["UNTIL"] = [until]
                    elif until.tzinfo is None or until.utcoffset() != timedelta(0):
                        fail("INVALID_RULE", "A zoned recurrence requires a UTC UNTIL value.", loc)
            slots = 1
            for key in ("BYHOUR", "BYMINUTE", "BYSECOND"):
                slots *= max(1, len(rule.get(key, [])))
            start_date = start.date() if isinstance(start, datetime) else start
            wanted = focus.get(
                "sha256:" + hashlib.sha256(str(uid).encode("utf-8")).hexdigest(), []
            )
            horizon = max([last, *wanted])
            if horizon.year > 2100 or any(day.year < 1600 for day in wanted):
                fail(
                    "EXPANSION_LIMIT",
                    "Requested original occurrence keys exceed supported years.",
                    loc,
                )
            scan_days = max(0, (horizon - start_date).days) + 7
            if not 1600 <= start_date.year <= 2100:
                fail(
                    "EXPANSION_LIMIT",
                    "Recurring DTSTART is outside supported years 1600..2100.",
                    loc,
                )
            # Conservative upper bounds before calling the expander. COUNT does
            # not reduce scan work: sparse rules can still scan many days.
            work += scan_days * slots * (1 + len(wanted))
            bound += min(
                scan_days * slots, int(rule.get("COUNT", [config["max_occurrences"] + 1])[0])
            )
        output_bound += bound
        if work > MAX_WORK or output_bound > config["max_occurrences"]:
            fail(
                "EXPANSION_LIMIT",
                "Conservative recurrence work or output bound exceeds the configured limit.",
                loc,
            )
        groups[str(uid)].append(event)
    for group in groups.values():
        masters = [e for e in group if "RECURRENCE-ID" not in e]
        if len(masters) > 1:
            equal = len({e.to_ical() for e in masters}) == 1
            fail(
                "DUPLICATE_IDENTITY" if equal else "AMBIGUOUS_IDENTITY",
                "More than one master event has the same UID; no copy is selected.",
                locations[id(masters[1])],
            )
        if not masters:
            fail(
                "ORPHAN_OVERRIDE",
                "A detached override has no master in this snapshot.",
                locations[id(group[0])],
            )
        master = masters[0]
        master_kind = _kind(master["DTSTART"].dt)
        seen = {}
        for event in group:
            if "RECURRENCE-ID" not in event:
                continue
            if _kind(event["RECURRENCE-ID"].dt) != master_kind:
                fail(
                    "DATE_TYPE_MISMATCH",
                    "Override identity has a different value type from its master.",
                    locations[id(event)],
                )
            key = _iso(event["RECURRENCE-ID"].dt)
            if key in seen:
                same = event.to_ical() == seen[key].to_ical()
                fail(
                    "DUPLICATE_IDENTITY" if same else "AMBIGUOUS_IDENTITY",
                    "Multiple overrides identify the same original occurrence.",
                    locations[id(event)],
                )
            seen[key] = event
    return groups, locations, timings


def _occurrence(event, key, location, override, series, timing):
    start = event["DTSTART"].dt
    return {
        "series": series,
        "kind": _kind(start),
        "key": key,
        "start": _iso(start),
        "end": _iso(_effective_end(start, timing)),
        "location": location,
        "override": override,
    }


def process(data: bytes, config: dict) -> dict:
    """Worker implementation; never use its global timezone state in a server."""
    raw_durations = _raw_preflight(data)
    # Force bundled, versioned tzdata rather than machine-specific OS tzdata.
    reset_tzpath([])
    ZoneInfo.clear_cache()
    from dateutil.tz import datetime_ambiguous, datetime_exists
    from icalendar import Calendar
    from icalendar.timezone import tzp
    from recurring_ical_events import CalendarQuery

    tzp.use_zoneinfo()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        calendar = Calendar.from_ical(data.decode("utf-8-sig"))
    groups, locations, timings = _preflight_calendar(calendar, config, raw_durations)
    first = datetime.fromisoformat(config["start"]).replace(tzinfo=timezone.utc)
    last = datetime.fromisoformat(config["end"]).replace(tzinfo=timezone.utc)
    results = {}
    for uid, group in groups.items():
        master = next(e for e in group if "RECURRENCE-ID" not in e)
        series = "sha256:" + hashlib.sha256(uid.encode("utf-8")).hexdigest()
        recurring = any("RRULE" in e or "RDATE" in e or "RECURRENCE-ID" in e for e in group)
        if not recurring:
            if str(master.get("STATUS", "")).upper() != "CANCELLED":
                results[(series, "single")] = _occurrence(
                    master, "single", locations[id(master)], False, series, timings[id(master)]
                )
            continue
        overrides = {_iso(e["RECURRENCE-ID"].dt): e for e in group if "RECURRENCE-ID" in e}
        # Only the sanitized event components go to the mature expansion engine.
        sub = Calendar()
        for event in group:
            sub.add_component(event)
        query = CalendarQuery(sub, keep_recurrence_attributes=True)
        # Expand a two-day margin to cover date-only and local timezone boundaries;
        # exact [start,end) filtering happens after matching both inputs.
        expanded = query.between(first - timedelta(days=2), last + timedelta(days=2))
        focus_keys = {item["key"] for item in config.get("focus", []) if item["series"] == series}
        already = {_iso(e["RECURRENCE-ID"].dt) for e in expanded}
        for focus_key in sorted(focus_keys - already):
            focus_date = datetime.fromisoformat(focus_key[:10]).replace(tzinfo=timezone.utc)
            candidates = query.between(
                focus_date - timedelta(days=2), focus_date + timedelta(days=3)
            )
            expanded.extend(e for e in candidates if _iso(e["RECURRENCE-ID"].dt) == focus_key)
        if len(expanded) > config["max_occurrences"]:
            fail("EXPANSION_LIMIT", "Expanded occurrences exceed the configured limit.")
        for event in expanded:
            value = event["DTSTART"].dt
            key = _iso(event["RECURRENCE-ID"].dt)
            original = overrides.get(key, master)
            if str(event.get("STATUS", "")).upper() == "CANCELLED":
                continue
            if isinstance(value, datetime):
                if not datetime_exists(value) or datetime_ambiguous(value):
                    # The pinned engine counts a generated gap toward COUNT;
                    # silently dropping it would claim an incorrect full result.
                    fail(
                        "AMBIGUOUS_LOCAL_TIME",
                        "An expanded occurrence is ambiguous or nonexistent at a clock change.",
                        locations[id(original)],
                    )
            item = _occurrence(
                event,
                key,
                locations[id(original)],
                key in overrides,
                series,
                timings[id(original)],
            )
            identity = (series, key)
            if identity in results:
                fail(
                    "AMBIGUOUS_OCCURRENCE",
                    "Expansion produced duplicate occurrence identities.",
                    locations[id(original)],
                )
            results[identity] = item
        # Include explicit overrides outside the query span so a move across a
        # window boundary can still be matched to its original occurrence.
        for key, event in overrides.items():
            if str(event.get("STATUS", "")).upper() != "CANCELLED":
                results[(series, key)] = _occurrence(
                    event, key, locations[id(event)], True, series, timings[id(event)]
                )
        if len(results) > config["max_occurrences"]:
            fail("EXPANSION_LIMIT", "Combined occurrences exceed the configured limit.")
    return {
        "event_count": sum(len(g) for g in groups.values()),
        "occurrence_count": len(results),
        "occurrences": list(results.values()),
        "complete": True,
        "issues": [],
    }


def main() -> None:
    # POSIX adds a memory ceiling. Windows still has all preflight/output bounds
    # and the parent wall-clock timeout; this is not an OS sandbox.
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    except (ImportError, OSError, ValueError):
        pass
    config = json.loads(sys.stdin.read(6 * 1024 * 1024))
    try:
        result = process(base64.b64decode(config.pop("data")), config)
    except Unsupported as exc:
        result = {
            "complete": False,
            "occurrences": [],
            "event_count": None,
            "occurrence_count": None,
            "issues": [issue(exc.code, config["source"], exc.message, exc.location)],
        }
    except Exception:
        # Parser exception messages can contain complete private content lines.
        result = {
            "complete": False,
            "occurrences": [],
            "event_count": None,
            "occurrence_count": None,
            "issues": [
                issue(
                    "PARSE_ERROR",
                    config["source"],
                    "Calendar parsing or expansion failed; no input content is included.",
                )
            ],
        }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
