# Compare two saved calendars

CalWitness compares occurrences in a finite window before and after an ICS export, import, or
migration. It helps answer: did a meeting disappear, appear twice, move, or change duration?
It reads local files and produces local JSON and HTML. It does not connect to a calendar account,
upload events, edit either input, or prove that an entire calendar was preserved.

[中文说明](README.zh-CN.md)

## Run locally

From a checkout of this project, with Python 3.10 or later:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. Installing dependencies may
use the network; comparing the installed tool's local ICS files is offline.

```sh
calwitness compare before.ics after.ics --from 2026-03-01 --until 2026-04-01 --json report.json --html report.html
```

Open `report.html` in a browser. It is a self-contained file with no scripts, remote fonts,
external assets, or tracking. Native disclosure controls expand identity evidence and collapse
groups of differences. You can use your browser's Find function for an occurrence key or issue code.
The JSON and HTML describe the same comparison; HTML does not independently expand or rematch events.

| Exit | Meaning |
| --- | --- |
| `0` | Complete comparison with no occurrence differences in the selected window. |
| `1` | Complete comparison with occurrence differences. This is an expected result when auditing a changed export. |
| `2` | Incomplete comparison, unsupported/invalid input, or a command/output error. Check the issues or error message. |

`--json -` writes JSON to standard output. `--max-occurrences N` and `--timeout SECONDS` bound
expansion work. Exceeding a bound produces an incomplete result, not a truncated clean comparison.
The conservative candidate-work bound can reject a dense or long-lived rule before the final
occurrence count reaches its limit; it is not merely a limit applied after expensive expansion.
Use `calwitness compare --help` to see the installed version's options and defaults.

## Try the synthetic migration

The bundled files contain invented events and no account data:

```sh
calwitness compare examples/before.ics examples/after.ics --from 2026-10-01 --until 2026-11-01 --json demo.json --html demo.html
```

Expect exit `1`, with **2 added, 1 removed, 1 moved, 2 duration changes and 1 unchanged**.
The after export loses a daily series' `EXDATE`, restoring a previously excluded instance;
it also loses a detached override, moving that instance back to the series time. A timed event
grows from one to two hours, an all-day event grows from one to two days, and one standalone
event is replaced with a different UID. Open the six difference cards to inspect those effects.
This is an intentional test fixture, not a measured failure of a particular calendar service.

The series spans the October 2026 clock change. To compare an equivalent timezone representation:

```sh
calwitness compare examples/before.ics examples/equivalent.ics --from 2026-10-01 --until 2026-11-01 --html equivalent.html
```

Expect exit `0`: the synthetic Berlin/Paris representations resolve to the same occurrences
in this window. This example does not imply that arbitrary timezone labels are interchangeable.

The [static demo](https://crown-sports.github.io/calwitness/) includes the changed comparison and a duplicate-identity case
that deliberately becomes incomplete. Rebuild these pages from the bundled synthetic inputs with
`python docs/demo/build.py` after installing this checkout. The builder calls the real comparison
API and asserts the expected status and counts; it does not hand-author result data. It accepts
no private calendar paths. Python/runtime provenance can differ between build environments.

## Read the result in this order

First check the verdict and window. The start is included and the end excluded: `[start,end)`.
Selection uses occurrence starts in either input. A matching occurrence may appear just outside
the window on the other side, allowing a boundary-crossing move to be shown. An occurrence that
only overlaps the window, but starts outside it in both inputs, is outside this audit.

Next inspect **Issues that affect interpretation**. Duplicate identities, unknown timezones,
unsupported recurrence rules and failed expansion make the comparison incomplete. A source issue
suppresses reported changes, preventing an expansion failure from looking like a list of lost events.
Zero difference cards in that situation is not evidence that the calendars agree.

Then review the side-by-side differences:

| Report label | Interpretation |
| --- | --- |
| Removed | A before occurrence has no matching after occurrence in the comparison. This is not a claim about every date in the calendar. |
| Added | An after occurrence has no matching before occurrence. A regenerated UID may appear as one removal and one addition. |
| Moved | Stable identity matched, but the occurrence's start changed. |
| Duration changed | Stable identity matched, but duration changed. |
| Moved and duration changed | Both changed for the same occurrence; it is shown once in this group. |
| Unchanged | Matched start and duration agree. Titles and other properties are not compared. |

Each card includes before/after start, end, displayed duration, source component location and
whether the instance is an override. Date-only values stay dates, with exclusive end dates.
Timed values are normalized instants. **Identity and matching evidence** shows the UID digest,
full occurrence key and match basis. The original UID is not displayed.

Matching uses stable UID plus the complete recurrence identity when applicable. It does not
pair events because titles look similar or times are nearby. A moved detached override retains
its original `RECURRENCE-ID`; its new `DTSTART` is not a replacement identity.
If the export rewrites UIDs, investigate that separately rather than treating fuzzy matching as proof.
Changing a nonrecurring event into `RRULE:FREQ=DAILY;COUNT=1` also changes its identity type:
even at the same time, it is reported as removed plus added rather than guessed across types.

Finally, check **Evidence and scope**: source byte counts, SHA-256 checksums, source event counts,
occurrence counts retained for matching, completeness and runtime versions. These source counts
can include nonrecurring events, explicit overrides and expansion margins outside the window;
they are not counts of selected differences. Checksums help identify exactly
which local files were compared. Structural locations such as `VEVENT[2]` help inspect the
corresponding component in those files without embedding event text in the report.
Counts from an incomplete source are shown as not established, rather than implying an empty calendar.

## Timezones and recurrence limits

Two timezone representations of the same instant are equivalent for this audit. A wrong timezone
that shifts the instant appears as a move; there is no separate guess that the timezone caused it.
Unresolved or ambiguous interpretation is an issue, not an assumed timezone conversion.

Floating date-times have no zone. If you know their intended interpretation, supply it explicitly:

```sh
calwitness compare before.ics after.ics --from 2026-03-01 --until 2026-04-01 --floating-zone Asia/Shanghai --html report.html
```

The same explicit choice applies to both inputs and is recorded in the report. `X-WR-TIMEZONE`
alone is not treated as authority for silently interpreting floating values. Ambiguous or nonexistent
local times, whether explicit or recurrence-generated, make comparison incomplete. The tool does
not guess an offset or silently skip a generated instance while claiming `COUNT` was preserved.

The first release covers daily, weekly, monthly and yearly recurrence, date/date-time `RDATE` and
`EXDATE`, and detached overrides within its supported rule subset. It explicitly rejects unsupported
constructs such as subdaily rules, `RDATE` periods and `RECURRENCE-ID;RANGE=...`. Unsupported
components, methods or timezone definitions are also surfaced as issues. A finite window and
successful expansion do not establish correctness for future years or every iCalendar feature.

| Example issue | What to check locally |
| --- | --- |
| `DUPLICATE_IDENTITY` | More than one identical component claims the same identity. |
| `AMBIGUOUS_IDENTITY` / `AMBIGUOUS_OCCURRENCE` | Conflicting candidates prevent a unique match. |
| `MISSING_UID` / `ORPHAN_OVERRIDE` | Stable series identity or the recurrence master is missing. |
| `FLOATING_TIME` / `UNKNOWN_TIMEZONE` | The file lacks an explicit, resolvable interpretation. |
| `AMBIGUOUS_LOCAL_TIME` | A local clock time has no unambiguous supported instant. |
| `UNSUPPORTED_RULE` / `UNSUPPORTED_RANGE` | The first release cannot safely interpret the construct. |
| `EXPANSION_LIMIT` / `WORKER_TIMEOUT` | The comparison did not finish within its explicit bounds. |

These are review findings, not automatic repair instructions. Keep the original files before
changing an export or migration process.

## Privacy and reproducibility

Reports omit source filenames, raw UIDs, summaries, descriptions, attendees and calendar text.
They still contain occurrence times, dates, structural locations, source checksums and UID digests.
This is data minimization, not anonymization: stable hashes can link records, and calendar times
can reveal private information. Review a report before sharing it. Rendering escapes all report
values as text and never turns calendar content into HTML, script, a link or a network request.

Save the source files privately with the JSON report and note the selected window and floating-zone
assumption. The runtime provenance records the versions involved; reproduce with those versions
when investigating different results after a dependency update. The original inputs remain the
source for properties this tool does not compare, including summaries, reminders and attendees.
