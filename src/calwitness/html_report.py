"""Self-contained HTML presentation of a CalWitness schema 1.0 comparison."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any

_KINDS = (
    ("removed", "Removed", "Present before, absent after within this window."),
    ("added", "Added", "Absent before, present after within this window."),
    ("moved", "Moved", "The matched occurrence starts at a different time."),
    ("duration_changed", "Duration changed", "The matched occurrence has a different duration."),
    ("moved_and_resized", "Moved and duration changed", "Both start and duration changed."),
)
_CSS = """
:root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont,
  'Segoe UI', sans-serif; color: #213447; background: #f5f7fa; line-height: 1.55; }
* { box-sizing: border-box; }
body { margin: 0; }
main { max-width: 1160px; margin: auto; padding: 40px 24px 56px; }
h1, h2, h3, p { margin-top: 0; }
h1 { font-size: clamp(1.8rem, 4vw, 2.7rem); line-height: 1.15; margin-bottom: 14px; }
h2 { font-size: 1.35rem; margin: 0 0 12px; }
h3 { font-size: 1rem; margin-bottom: 8px; }
p { margin-bottom: 12px; }
small, .muted { color: #52677a; }
a { color: #245d82; text-underline-offset: 3px; }
a:focus-visible, summary:focus-visible { outline: 3px solid #457e9d; outline-offset: 4px; }
code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .88em; }
code, dd, time { overflow-wrap: anywhere; }
.eyebrow { color: #52677a; letter-spacing: .1em; text-transform: uppercase; font-size: .76rem; }
.example { padding: 12px 15px; border: 1px solid #cbdde8; border-radius: 8px;
  background: #edf5fa; font-size: .88rem; }
.lead { max-width: 78ch; color: #52677a; }
.nav { display: flex; flex-wrap: wrap; gap: 20px; margin: 20px 0 28px; }
.panel, .change-group, .issue { background: #fff; border: 1px solid #d9e2e9; border-radius: 12px; }
.panel { padding: 22px; margin-bottom: 20px; }
.verdict { border-left: 5px solid #40708c; }
.verdict.clean { border-left-color: #23724e; background: #f3faf6; }
.verdict.incomplete { border-left-color: #a86d20; background: #fff9ef; }
.window { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.window p { margin: 4px 0; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(125px, 1fr)); gap: 10px;
  margin: 22px 0 32px; }
.metric { background: #fff; border: 1px solid #d9e2e9; border-radius: 10px; padding: 14px; }
.metric strong { display: block; font-size: 1.8rem; font-weight: 650; line-height: 1.2; }
.metric span { display: block; font-size: .8rem; color: #52677a; margin-top: 6px; }
section { margin-bottom: 32px; scroll-margin-top: 20px; }
.issue { padding: 16px 18px; margin: 10px 0; border-left: 4px solid #a86d20; }
.issue p:last-child { margin-bottom: 0; }
.tag { display: inline-block; border: 1px solid #d9e2e9; border-radius: 5px; padding: 1px 7px;
  font-size: .75rem; font-weight: 600; vertical-align: middle; margin-right: 8px; }
.change-group { margin: 14px 0; overflow: hidden; }
.change-group > summary { padding: 17px 20px; font-weight: 650; cursor: pointer; }
.change-group > p { margin: 0 20px 15px; color: #52677a; font-size: .9rem; }
.change { border-top: 1px solid #e2e8ed; padding: 20px; }
.change-head { display: flex; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.pair, .sources { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.occurrence { border: 1px solid #e2e8ed; border-radius: 8px; padding: 16px; min-width: 0; }
.occurrence.after { background: #f7fafc; }
.absent { color: #52677a; }
dl { margin: 0; }
dt { color: #52677a; font-size: .78rem; margin-top: 9px; }
dd { margin: 2px 0 0; }
.identity { margin-top: 14px; font-size: .85rem; }
.identity summary { cursor: pointer; color: #245d82; }
.identity dl { padding: 4px 0; }
.sources .panel { margin: 0; }
.evidence-note, footer { font-size: .85rem; color: #52677a; }
footer { border-top: 1px solid #d9e2e9; padding-top: 20px; }
@media (max-width: 640px) {
  main { padding: 26px 16px 40px; }
  .pair, .sources, .window { grid-template-columns: 1fr; }
  .panel, .change { padding: 17px; }
  .window { gap: 12px; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media print {
  :root { background: white; }
  main { max-width: none; padding: 0; }
  .nav { display: none; }
  .change, .issue, .panel { break-inside: avoid; }
}
"""


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _duration(occurrence: dict) -> str:
    """Display the serialized interval without re-expanding or matching events."""
    try:
        if occurrence["kind"] == "date":
            days = (
                date.fromisoformat(occurrence["end"]) - date.fromisoformat(occurrence["start"])
            ).days
            return f"{days} day" + ("s" if days != 1 else "")
        start = datetime.fromisoformat(occurrence["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(occurrence["end"].replace("Z", "+00:00"))
        seconds = int((end - start).total_seconds())
        sign = "−" if seconds < 0 else ""
        hours, remainder = divmod(abs(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if hours:
            parts.append(f"{hours} h")
        if minutes:
            parts.append(f"{minutes} min")
        if seconds or not parts:
            parts.append(f"{seconds} s")
        return sign + " ".join(parts)
    except (KeyError, TypeError, ValueError):
        return "Unavailable"


def _occurrence(value: dict | None, side: str) -> str:
    label = "Before" if side == "before" else "After"
    if value is None:
        return (
            f'<div class="occurrence {side}"><h3>{label}</h3>'
            '<p class="absent">No occurrence on this side of the selected window.</p></div>'
        )
    kind = "Date-only event · end date is exclusive" if value["kind"] == "date" else "UTC instant"
    origin = "Recurrence override" if value.get("override") else "Original or generated occurrence"
    return (
        f'<div class="occurrence {side}"><h3>{label}</h3><p class="muted">{kind}</p><dl>'
        f"<dt>Start</dt><dd><time>{_e(value['start'])}</time></dd>"
        f"<dt>End</dt><dd><time>{_e(value['end'])}</time></dd>"
        f"<dt>Duration</dt><dd>{_e(_duration(value))}</dd>"
        f"<dt>Source component</dt><dd><code>{_e(value['location'])}</code> · {origin}</dd>"
        "</dl></div>"
    )


def _change(value: dict, number: int) -> str:
    matching = {
        "uid": "UID identity",
        "uid+recurrence-id": "UID + recurrence identity",
    }.get(value["matching"], value["matching"])
    return (
        '<article class="change"><div class="change-head">'
        f'<h3>Occurrence {number}</h3><span class="muted">{_e(matching)}</span></div>'
        f'<div class="pair">{_occurrence(value["before"], "before")}'
        f"{_occurrence(value['after'], 'after')}</div>"
        '<details class="identity"><summary>Identity and matching evidence</summary><dl>'
        f"<dt>UID digest</dt><dd><code>{_e(value['series'])}</code></dd>"
        f"<dt>Full occurrence key</dt><dd><code>{_e(value['key'])}</code></dd>"
        "<dt>Match basis</dt>"
        f"<dd>{_e(matching)}. No match was inferred from a title or nearby time.</dd>"
        "</dl></details></article>"
    )


def _issue(value: dict) -> str:
    source = {"before": "Before", "after": "After", "comparison": "Comparison"}.get(
        value["source"], value["source"]
    )
    return (
        '<article class="issue">'
        f'<h3><span class="tag">{_e(value["severity"])}</span>'
        f"<code>{_e(value['code'])}</code></h3>"
        f'<p>{_e(value["message"])}</p><p class="muted">{_e(source)} · '
        f"<code>{_e(value['location'])}</code></p></article>"
    )


def _source(value: dict, label: str) -> str:
    complete = "Complete for supported input in this window" if value["complete"] else "Incomplete"
    events = (
        _e(value["event_count"]) if value["complete"] else "Not established (input incomplete)"
    )
    occurrences = (
        _e(value["occurrence_count"])
        if value["complete"]
        else "Not established (input incomplete)"
    )
    return (
        f'<div class="panel"><h3>{label}</h3><dl>'
        f"<dt>Expansion</dt><dd>{complete}</dd>"
        f"<dt>Source VEVENTs</dt><dd>{events}</dd>"
        f"<dt>Occurrences retained for matching</dt><dd>{occurrences}</dd>"
        f"<dt>Input bytes</dt><dd>{_e(value['bytes'])}</dd>"
        f"<dt>Source SHA-256</dt><dd><code>{_e(value['sha256'])}</code></dd>"
        "</dl></div>"
    )


def render_html(report: dict, *, synthetic: bool = False) -> str:
    """Render schema 1.0 data without IO, external resources, or executable input."""
    if report["schema_version"] != "1.0":
        raise ValueError("Unsupported report schema.")
    if any(value["kind"] not in {kind for kind, _, _ in _KINDS} for value in report["changes"]):
        raise ValueError("Unsupported difference kind; report would omit comparison data.")
    window = report["window"]
    summary = report["summary"]
    incomplete = report["complete"] is not True or report["status"] == "incomplete"
    if incomplete:
        status, title = "incomplete", "Comparison incomplete"
        explanation = (
            "Some input could not be compared reliably. Review the issues first. "
            "Reported differences, if any, are partial evidence; "
            "zero differences is not a clean result."
        )
    elif report["changes"]:
        status, title = "changed", "Occurrence differences found"
        explanation = (
            "Review the before and after values below. These findings apply only to this window."
        )
    else:
        status, title = "clean", "No occurrence differences in this window"
        explanation = (
            "Supported occurrences compared without drift. This does not establish "
            "equivalence outside the window or preservation of other calendar properties."
        )
    zone = window.get("floating_zone")
    zone_text = (
        f"Floating times use the explicitly selected zone: <code>{_e(zone)}</code>."
        if zone
        else "No floating-time interpretation zone was supplied."
    )
    metrics = [
        '<div class="metric"><strong>'
        + _e(summary.get(kind, 0))
        + "</strong><span>"
        + label
        + "</span></div>"
        for kind, label in (
            ("removed", "Removed"),
            ("added", "Added"),
            ("moved", "Moved"),
            ("duration_changed", "Duration changed"),
            ("moved_and_resized", "Moved + duration"),
            ("unchanged", "Unchanged"),
            ("issues", "Issues"),
        )
    ]
    issues = "".join(_issue(item) for item in report["issues"])
    if not issues:
        issues = '<p class="muted">No comparison issues were reported.</p>'
    groups = []
    for kind, label, meaning in _KINDS:
        items = [
            (index, value)
            for index, value in enumerate(report["changes"], 1)
            if value["kind"] == kind
        ]
        if items:
            groups.append(
                f'<details class="change-group" open><summary>{label} · {len(items)}</summary>'
                f"<p>{meaning}</p>"
                + "".join(_change(item, index) for index, item in items)
                + "</details>"
            )
    if not groups:
        groups.append(
            '<div class="panel"><p>'
            + (
                "No difference entries are available. The comparison remains incomplete."
                if incomplete
                else "No occurrence differences were identified."
            )
            + "</p></div>"
        )
    limits = " · ".join(
        f"{_e(key)}: {_e(value)}" for key, value in report.get("limits", {}).items()
    )
    provenance = " · ".join(
        f"{_e(key)}: {_e(value)}" for key, value in report["provenance"].items()
    )
    example = (
        '<p class="example"><strong>Synthetic example / 人工示例</strong><br>'
        "Generated from bundled invented calendars, without real account data. "
        "仅使用人工构造的日历，无真实账户数据。 "
        '<a href="index.html">All examples / 示例目录</a></p>'
        if synthetic
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>CalWitness — occurrence comparison</title><style>{_CSS}</style></head><body><main>
<header><p class="eyebrow">CalWitness · local calendar comparison</p>
{example}
<h1>What changed in this calendar?</h1>
<p class="lead">Before and after occurrences, matched by stable identity.
A finite-window audit of saved ICS files; no guessed matches.</p>
<nav class="nav" aria-label="Report sections"><a href="#issues">Issues</a>
<a href="#differences">Differences</a><a href="#evidence">Evidence and scope</a></nav></header>
<section class="panel verdict {status}" aria-label="Comparison result">
<h2>{title}</h2><p>{explanation}</p></section>
<section class="panel" aria-label="Comparison window">
<h2>Comparison window</h2><div class="window">
<div><small>Start · included</small><p><time>{_e(window["start"])}</time></p></div>
<div><small>End · excluded</small><p><time>{_e(window["end"])}</time></p></div></div>
<p class="muted">Selection: {_e(window["selection"])}, using
<code>{_e(window["bounds"])}</code> bounds. A matched counterpart may fall outside this window.</p>
<p class="muted">{zone_text}</p></section>
<div class="metrics" aria-label="Comparison counts">{"".join(metrics)}</div>
<section id="issues"><h2>Issues that affect interpretation</h2>{issues}</section>
<section id="differences">
<h2>{"Known differences" if incomplete else "Occurrence differences"}</h2>
{"".join(groups)}</section>
<section id="evidence"><h2>Evidence and scope</h2><div class="sources">
{_source(report["sources"]["before"], "Before source")}
{_source(report["sources"]["after"], "After source")}</div>
<div class="panel" style="margin-top: 16px"><h3>How to interpret this report</h3>
<p>Duplicate or ambiguous identities are issues, not guessed matches. Inspect the original source
component locally using its location and the source checksum.</p>
<p>Source occurrence counts include candidates retained outside the selected window for matching,
including explicit overrides and expansion margins. The difference counts apply to the window.</p>
<p>Equivalent timezone representations of the same instant are not drift. A timezone change that
shifts an instant appears as a move; unresolved time interpretation makes the comparison
incomplete.</p>
<p>Date-only values remain calendar dates. Instant values are normalized for comparison.
Titles, descriptions, attendees and reminders are outside this occurrence comparison.</p>
<p class="evidence-note">Raw UIDs, calendar text and source filenames are omitted.
UID digests, occurrence times and structural locations can still reveal information;
treat this report as private unless reviewed.</p>
</div><p class="evidence-note">Configured limits: {limits or "Not recorded"}</p>
<p class="evidence-note">Runtime provenance: {provenance}</p></section>
<footer>{_e(report["tool"]["name"])} {_e(report["tool"]["version"])} ·
Report schema {_e(report["schema_version"])}. Self-contained HTML;
no scripts, remote fonts, assets or tracking. Opening this report sends no calendar data.</footer>
</main></body></html>
"""
