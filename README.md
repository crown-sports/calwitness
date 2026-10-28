# CalWitness

**Find lost exceptions, shifted meetings and duration changes after a calendar export.**

A daily meeting still has the same UID and recurrence rule after migration, but its moved Sunday
instance has reverted to the original time. CalWitness expands supported occurrences in two local
ICS files, matches their identities, and shows the before/after times in a self-contained report.

It runs offline after installation. No calendar account, API key, upload or input modification.
Version 0.1.0 is an early preview with explicit limits; an incomplete result never counts as a pass.

[Read the report](docs/report.md) · [中文说明](docs/README.zh-CN.md) ·
[Synthetic reports](https://crown-sports.github.io/calwitness/) ·
[Releases](https://github.com/crown-sports/calwitness/releases)

## Try a calendar with lost exceptions

Python 3.10 or later. Install the checkout in a virtual environment:

```sh
git clone https://github.com/crown-sports/calwitness.git
cd calwitness
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
calwitness compare examples/before.ics examples/after.ics --from 2026-10-01 --until 2026-11-01 --json report.json --html report.html
```

Open `report.html`. The synthetic example contains **2 added occurrences, 1 removed occurrence,
1 moved occurrence, 2 duration changes and 1 unchanged occurrence**. Exit code `1` is expected:
the comparison completed and found differences.

The changed export lost an `EXDATE` and a detached override across Berlin's autumn clock change.
It also lengthened a timed meeting and an all-day event, removed one event and added another.
The report keeps each finding tied to the input's `VEVENT` position without displaying its title.

For an equivalent export with different property order and timestamps:

```sh
calwitness compare examples/before.ics examples/equivalent.ics --from 2026-10-01 --until 2026-11-01
```

This returns `0`: the five selected occurrences have the same starts and durations.
The examples are constructed test data, not evidence of a successful real account migration.
You can also install a wheel from Releases. The package is not published on PyPI.

## Compare your own exports

```sh
calwitness compare before.ics after.ics --from 2026-01-01 --until 2027-01-01 --json comparison.json --html comparison.html
```

The window includes its start and excludes its end. Timed events use UTC midnight boundaries;
all-day events use the corresponding dates and retain their exclusive end dates. An occurrence
is selected when its start is in the window in either input. Events that only overlap the window
while starting outside it are not selected.

| Exit | Result | Meaning |
| --- | --- | --- |
| `0` | Clean | The supported occurrences agree inside the selected window. |
| `1` | Changed | Added, removed, moved or resized occurrences were found. |
| `2` | Incomplete or command error | Check the issues; no successful comparison is claimed. |

Use `--json -` for machine-readable standard output. If the files contain floating times, supply
their intended IANA zone explicitly with `--floating-zone Asia/Shanghai`. The same choice applies
to both inputs and is recorded in the report. The machine's local timezone is never guessed.

## What a match proves

Single events match by UID. Recurring instances match by UID and the **full original recurrence
identity**, not a UTC day, sequence number, similar title or nearby start. A detached override
retains its original `RECURRENCE-ID` even when it moves. Equivalent timezone representations
of the same instant agree. A changed recurrence rule can produce additions and removals when
the original identities change; the tool does not invent moved pairs.

Duplicate or conflicting identities, unknown timezones, unsupported constructs, or exhausted
resource limits make the comparison incomplete. A failed source suppresses change findings so
parser failure cannot look like a calendar full of deleted meetings.

Reports omit raw UIDs, filenames, titles, descriptions and attendees. They retain times, dates,
component positions, source SHA-256 checksums and stable UID digests. **This is not anonymization:**
times and hashes can reveal or link private records. Review reports before sharing them.

## Supported scope and limits

- UTF-8 `VCALENDAR` snapshots with `VEVENT` and embedded `VTIMEZONE`; all-day and timed events.
- Daily, weekly, monthly and yearly rules, date/date-time `RDATE` and `EXDATE`, and detached
  overrides within the documented subset.
- Independent parser processes per input, pinned timezone data, recorded dependency versions,
  pre-expansion work bounds and a worker deadline.
- Self-contained JSON and HTML reports. The HTML uses no scripts, external assets or tracking.

Subdaily rules, `RDATE` periods, `RECURRENCE-ID;RANGE=...`, unresolved or ambiguous local times,
and other unsupported input produce an incomplete result. The tool has file, event, occurrence,
window and expansion-work limits; raising the occurrence cap does not disable the other limits.
See [the complete interpretation and privacy guide](docs/report.md).

CalWitness does not compare titles, reminders, attendees or every iCalendar property. It does
not repair calendars, operate a sync service, or establish whole-calendar equivalence outside
the selected window. A clean result does not prove that Google Calendar, Outlook or Apple
Calendar will import or display a file identically.

## Building on existing tools

[icalendar](https://github.com/collective/icalendar) supplies parsing and embedded timezone support;
[recurring-ical-events](https://github.com/niccokunzmann/python-recurring-ical-events) supplies
recurrence expansion. CalWitness adds bounded comparison, identity matching and report evidence.

For field-level comparison, [FindUtils ICS Diff](https://findutils.com/convert/ics-diff/) describes
comparing recurrence rules as fields, with occurrence expansion as a separate step.
[PowMCP Calendar File Check](https://powmcp.com/apps/ics-calendar-check/) describes validating
public feeds without matching corresponding events for start/end drift. These are different
checks; CalWitness is not a general RFC conformance validator.

## Development and feedback

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check .
ruff format --check .
python -m build
```

Useful reports include the smallest **synthetic** before/after calendars, the window, the expected
occurrence and the tool version. Do not post personal calendar exports. Regression cases involving
exporter behavior, timezone transitions and recurrence exceptions are welcome.
