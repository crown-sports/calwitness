"""Command-line entry point. No input calendar is ever rewritten."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__, compare_calendars
from .compare import MAX_BYTES


def text_report(report: dict) -> str:
    lines = [
        f"CalWitness {report['status'].upper()} — complete={str(report['complete']).lower()}",
        f"Window: {report['window']['start']} <= start < {report['window']['end']} (either input)",
    ]
    summary = report["summary"]
    lines.append(
        "Occurrences: "
        + ", ".join(
            f"{key}={summary[key]}"
            for key in (
                "added",
                "removed",
                "moved",
                "duration_changed",
                "moved_and_resized",
                "unchanged",
            )
        )
    )
    for item in report["issues"]:
        lines.append(f"{item['code']} {item['source']} {item['location']}: {item['message']}")
    for change in report["changes"][:30]:
        before, after = change["before"], change["after"]
        lines.append(
            f"{change['kind']} {change['series'][:23]} {change['key']}: "
            f"{before['start'] if before else '—'} -> {after['start'] if after else '—'}"
        )
    if len(report["changes"]) > 30:
        lines.append("Only the first 30 differences are shown; use --json or --html for all.")
    return "\n".join(lines)


def _write(path: Path, content: str) -> None:
    # Atomic replacement avoids leaving a half-written evidence report.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare finite-window iCalendar occurrences offline."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("compare", help="Compare two UTF-8 calendar snapshots.")
    command.add_argument("before", type=Path)
    command.add_argument("after", type=Path)
    command.add_argument(
        "--from", dest="start", required=True, help="Inclusive UTC date, YYYY-MM-DD."
    )
    command.add_argument(
        "--until", dest="end", required=True, help="Exclusive UTC date, YYYY-MM-DD."
    )
    command.add_argument(
        "--floating-zone", help="Exact IANA timezone for floating DATE-TIME values."
    )
    command.add_argument("--max-occurrences", type=int, default=10_000)
    command.add_argument(
        "--timeout", type=float, default=10.0, help="Seconds per isolated input worker (<=30)."
    )
    command.add_argument(
        "--json", dest="json_path", help="Write JSON to a file, or '-' for stdout."
    )
    command.add_argument("--html", type=Path, help="Write a self-contained HTML report.")
    args = parser.parse_args(argv)
    outputs = [Path(args.json_path)] if args.json_path and args.json_path != "-" else []
    if args.html:
        outputs.append(args.html)
    try:
        inputs = {args.before.resolve(), args.after.resolve()}
        resolved = [p.resolve() for p in outputs]
        if inputs.intersection(resolved) or len(set(resolved)) != len(resolved):
            parser.error("Report paths must differ from input paths and from each other.")
        # Reject hardlink aliases as well as symlinks to either input.
        for output in outputs:
            if output.exists() and any(output.samefile(p) for p in (args.before, args.after)):
                parser.error("A report path aliases an input calendar.")
        data = []
        for path in (args.before, args.after):
            if not path.is_file():
                raise ValueError("Calendar inputs must be regular files.")
            with path.open("rb") as stream:
                data.append(stream.read(MAX_BYTES + 1))
        report = compare_calendars(
            *data,
            start=args.start,
            end=args.end,
            floating_zone=args.floating_zone,
            max_occurrences=args.max_occurrences,
            timeout=args.timeout,
        )
        encoded = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        if args.json_path == "-":
            print(encoded, end="")
        elif args.json_path:
            _write(Path(args.json_path), encoded)
        if args.html:
            from .html_report import render_html

            _write(args.html, render_html(report))
        if args.json_path != "-":
            print(text_report(report))
        return {"clean": 0, "changed": 1, "incomplete": 2}[report["status"]]
    except (OSError, ValueError):
        # Paths, input fragments, and exceptions may contain private information.
        print(
            "CalWitness: invalid options, unreadable input, or unwritable report. "
            "No successful comparison is claimed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
