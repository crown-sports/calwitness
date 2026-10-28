"""Public comparison API and isolated parser orchestration."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import date, datetime, timezone

MAX_BYTES = 4 * 1024 * 1024
MAX_EVENTS = 1000
MAX_WINDOW_DAYS = 3660
MAX_WORK = 200_000
DEFAULT_OCCURRENCES = 10_000
KINDS = ("added", "removed", "moved", "duration_changed", "moved_and_resized")


def issue(code: str, source: str, message: str, location: str = "VCALENDAR") -> dict:
    return {
        "code": code,
        "severity": "error",
        "source": source,
        "location": location,
        "message": message,
    }


def _source(data: bytes, side: str, config: dict) -> dict:
    result = {
        "sha256": hashlib.sha256(data).hexdigest() if len(data) <= MAX_BYTES else None,
        "bytes": len(data),
        "event_count": None,
        "occurrence_count": None,
        "complete": False,
        "occurrences": [],
        "issues": [],
    }
    if len(data) > MAX_BYTES:
        result["issues"] = [issue("INPUT_LIMIT", side, "Input exceeds the 4 MiB limit.")]
        return result
    request = dict(config, data=base64.b64encode(data).decode("ascii"), source=side)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-m", "calwitness.worker"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=config["timeout"],
            check=False,
        )
    except subprocess.TimeoutExpired:
        result["issues"] = [
            issue("WORKER_TIMEOUT", side, "Calendar processing exceeded the wall-clock limit.")
        ]
        return result
    except OSError:
        result["issues"] = [issue("WORKER_FAILED", side, "Could not start the parser worker.")]
        return result
    if proc.returncode != 0:
        result["issues"] = [
            issue(
                "WORKER_FAILED",
                side,
                "The isolated parser worker failed; comparison is incomplete.",
            )
        ]
        return result
    try:
        result.update(json.loads(proc.stdout))
    except (ValueError, TypeError):
        result["issues"] = [issue("WORKER_FAILED", side, "The parser worker returned no report.")]
    return result


def _duration(item: dict) -> float:
    parser = date.fromisoformat if item["kind"] == "date" else datetime.fromisoformat
    return (
        parser(item["end"].replace("Z", "+00:00")) - parser(item["start"].replace("Z", "+00:00"))
    ).total_seconds()


def _in_window(item: dict, start: date, end: date) -> bool:
    if item["kind"] == "date":
        return start <= date.fromisoformat(item["start"]) < end
    value = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
    return (
        datetime.combine(start, datetime.min.time(), timezone.utc)
        <= value
        < (datetime.combine(end, datetime.min.time(), timezone.utc))
    )


def compare_calendars(
    before: bytes,
    after: bytes,
    *,
    start: str,
    end: str,
    floating_zone: str | None = None,
    max_occurrences: int = DEFAULT_OCCURRENCES,
    timeout: float = 10.0,
) -> dict:
    """Compare bytes within [start, end); dates are YYYY-MM-DD UTC boundaries.

    Inputs are independently parsed in isolated subprocesses. No event content is
    included in diagnostics. Invalid API options raise ValueError; invalid ICS
    returns an incomplete report. Nothing is written or fetched from the network.
    """
    if not isinstance(before, bytes) or not isinstance(after, bytes):
        raise TypeError("Calendar inputs must be bytes.")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Window dates must use YYYY-MM-DD.") from exc
    if start != first.isoformat() or end != last.isoformat():
        raise ValueError("Window dates must use YYYY-MM-DD.")
    if not 0 < (last - first).days <= MAX_WINDOW_DAYS:
        raise ValueError("Window must contain 1 to 3660 days.")
    if not 1900 <= first.year <= last.year <= 2100:
        raise ValueError("Window must be within years 1900 through 2100.")
    if isinstance(max_occurrences, bool) or not isinstance(max_occurrences, int):
        raise ValueError("Occurrence limit must be an integer.")
    if not 1 <= max_occurrences <= 50_000 or not 0 < timeout <= 30:
        raise ValueError("Occurrence limit must be 1..50000; timeout must be >0 and <=30.")
    if floating_zone is not None and (not isinstance(floating_zone, str) or not floating_zone):
        raise ValueError("Floating timezone must be a nonempty IANA name.")
    config = {
        "start": start,
        "end": end,
        "floating_zone": floating_zone,
        "max_occurrences": max_occurrences,
        "timeout": timeout,
    }
    sources = {
        "before": _source(before, "before", config),
        "after": _source(after, "after", config),
    }
    if all(s["complete"] for s in sources.values()):
        # A moved-in override may refer to an original slot far outside the
        # window. Ask fresh workers for those exact keys; never match by ordinal.
        focus = sorted(
            {
                (o["series"], o["key"])
                for src in sources.values()
                for o in src["occurrences"]
                if o["override"]
            }
        )
        if focus:
            config["focus"] = [{"series": series, "key": key} for series, key in focus]
            for side, data in (("before", before), ("after", after)):
                existing = {(o["series"], o["key"]) for o in sources[side]["occurrences"]}
                if any(key not in existing for key in focus):
                    sources[side] = _source(data, side, config)
    issues = sources["before"]["issues"] + sources["after"]["issues"]
    complete = all(s["complete"] for s in sources.values())
    summary = dict.fromkeys(KINDS, 0)
    summary.update(unchanged=0, issues=len(issues))
    changes = []
    # Avoid reporting spurious losses from an input we could not fully interpret.
    if complete:
        indices = {
            side: {(o["series"], o["key"]): o for o in src["occurrences"]}
            for side, src in sources.items()
        }
        for identity in sorted(indices["before"].keys() | indices["after"].keys()):
            a, b = indices["before"].get(identity), indices["after"].get(identity)
            if not any(_in_window(o, first, last) for o in (a, b) if o is not None):
                continue
            if a is None:
                kind = "added"
            elif b is None:
                kind = "removed"
            elif a["kind"] != b["kind"]:
                # DATE versus DATE-TIME has no defensible time delta.
                issues.append(
                    issue(
                        "TYPE_CHANGED",
                        "comparison",
                        "A matched event changed between DATE and DATE-TIME.",
                        a["location"],
                    )
                )
                complete = False
                continue
            else:
                moved = a["start"] != b["start"]
                resized = _duration(a) != _duration(b)
                if not moved and not resized:
                    summary["unchanged"] += 1
                    continue
                kind = (
                    "moved_and_resized"
                    if moved and resized
                    else "moved"
                    if moved
                    else "duration_changed"
                )
            summary[kind] += 1
            changes.append(
                {
                    "kind": kind,
                    "series": identity[0],
                    "key": identity[1],
                    "before": a,
                    "after": b,
                    "matching": "uid" if identity[1] == "single" else "uid+recurrence-id",
                }
            )
    summary["issues"] = len(issues)
    versions = {
        name.replace("-", "_"): importlib.metadata.version(name)
        for name in (
            "icalendar",
            "recurring-ical-events",
            "tzdata",
            "python-dateutil",
            "x-wr-timezone",
        )
    }
    for src in sources.values():
        src.pop("occurrences")
        src.pop("issues")
    from . import __version__

    return {
        "schema_version": "1.0",
        "tool": {"name": "calwitness", "version": __version__},
        "status": "incomplete" if not complete else "changed" if changes else "clean",
        "complete": complete,
        "window": {
            "start": start + "T00:00:00Z",
            "end": end + "T00:00:00Z",
            "bounds": "[start,end)",
            "selection": "occurrence start in either input",
            "floating_zone": floating_zone,
        },
        "limits": {
            "input_bytes": MAX_BYTES,
            "events": MAX_EVENTS,
            "occurrences": max_occurrences,
            "candidate_work": MAX_WORK,
            "worker_timeout_seconds": timeout,
        },
        "provenance": {
            "python": platform.python_version(),
            **versions,
            "timezone_source": "pinned tzdata and embedded VTIMEZONE",
        },
        "sources": sources,
        "summary": summary,
        "changes": changes,
        "issues": issues,
    }
