"""Renderer checks use synthetic schema objects; core comparisons have separate tests."""

from copy import deepcopy
from html.parser import HTMLParser

import pytest

from calwitness.html_report import render_html


def sample_report():
    source = {
        "sha256": "a" * 64,
        "bytes": 123,
        "event_count": 1,
        "occurrence_count": 1,
        "complete": True,
    }
    return {
        "schema_version": "1.0",
        "tool": {"name": "calwitness", "version": "0.1.0"},
        "status": "clean",
        "complete": True,
        "window": {
            "start": "2026-03-01T00:00:00+00:00",
            "end": "2026-04-01T00:00:00+00:00",
            "bounds": "[start,end)",
            "selection": "occurrence start in either input",
            "floating_zone": None,
        },
        "provenance": {"python": "3.12", "icalendar": "7.3.0"},
        "sources": {"before": deepcopy(source), "after": deepcopy(source)},
        "summary": {
            "added": 0,
            "removed": 0,
            "moved": 0,
            "duration_changed": 0,
            "moved_and_resized": 0,
            "unchanged": 1,
            "issues": 0,
        },
        "changes": [],
        "issues": [],
    }


def occurrence(start="2026-03-02T10:00:00+00:00", end="2026-03-02T11:30:00+00:00"):
    return {
        "kind": "instant",
        "key": "single",
        "start": start,
        "end": end,
        "location": "VEVENT[0]",
        "override": False,
    }


def change(kind, before=None, after=None):
    return {
        "kind": kind,
        "series": "sha256:" + "a" * 64,
        "key": "single",
        "before": before,
        "after": after,
        "matching": "uid",
    }


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_clean_report_has_exact_window_and_no_remote_or_executable_resources():
    report = sample_report()
    result = render_html(report)
    parser = Elements()
    parser.feed(result)
    assert "No occurrence differences in this window" in result
    assert report["window"]["start"] in result
    assert report["window"]["end"] in result
    assert "End · excluded" in result
    assert "Selection: occurrence start in either input" in result
    assert "not establish" in result
    for tag, attrs in parser.elements:
        assert tag not in {"script", "iframe", "img", "link", "form", "object", "embed"}
        assert not any(key.startswith("on") for key in attrs)
        assert "src" not in attrs
        if "href" in attrs:
            assert attrs["href"].startswith("#")
    assert "default-src 'none'" in result


def test_incomplete_zero_changes_cannot_look_clean():
    report = sample_report()
    report["complete"] = False
    report["sources"]["before"]["complete"] = False
    report["sources"]["before"]["event_count"] = None
    report["sources"]["before"]["occurrence_count"] = None
    report["issues"] = [
        {
            "code": "DUPLICATE_IDENTITY",
            "severity": "error",
            "source": "before",
            "location": "VEVENT[1]",
            "message": "Multiple components claim the same identity.",
        }
    ]
    report["summary"]["issues"] = 1
    result = render_html(report)
    assert "Comparison incomplete" in result
    assert "zero differences is not a clean result" in result
    assert "No occurrence differences in this window" not in result
    assert result.index("DUPLICATE_IDENTITY") < result.index('id="differences"')
    assert "Known differences" in result
    assert "Not established (input incomplete)" in result
    assert "No difference entries are available" in result


def test_all_difference_kinds_and_matching_evidence_are_visible():
    report = sample_report()
    report["status"] = "changed"
    for kind in ("added", "removed", "moved", "duration_changed", "moved_and_resized"):
        report["changes"].append(change(kind, occurrence(), occurrence()))
        report["summary"][kind] = 1
    report["changes"][0]["before"] = None
    report["changes"][1]["after"] = None
    report["changes"][2]["matching"] = "uid+recurrence-id"
    report["changes"][2]["key"] = "2026-03-02T10:00:00+00:00"
    report["changes"][2]["after"]["override"] = True
    result = render_html(report)
    assert result.count('<article class="change">') == 5
    assert "Moved and duration changed · 1" in result
    assert "No occurrence on this side of the selected window" in result
    assert "1 h 30 min" in result
    assert "UID + recurrence identity" in result
    assert "Recurrence override" in result
    assert "No match was inferred from a title or nearby time" in result


def test_date_only_intervals_stay_dates_and_explain_exclusive_end():
    report = sample_report()
    item = occurrence("2026-03-02", "2026-03-04")
    item["kind"] = "date"
    report["changes"] = [change("added", after=item)]
    result = render_html(report)
    assert "Date-only event · end date is exclusive" in result
    assert "2 days" in result
    assert "2026-03-02T" not in result


def test_untrusted_report_values_are_text_not_markup():
    report = sample_report()
    attack = '</style><script>alert("uid")</script><img src="https://evil.invalid/" onerror="x">'
    value = occurrence(attack, attack)
    value["location"] = attack
    report["changes"] = [change("moved", value, value)]
    report["changes"][0].update(series=attack, key=attack, matching=attack)
    report["window"]["floating_zone"] = attack
    report["tool"]["name"] = attack
    report["provenance"][attack] = attack
    report["sources"]["before"]["sha256"] = attack
    report["issues"] = [
        {
            "code": attack,
            "severity": attack,
            "source": attack,
            "location": attack,
            "message": attack,
        }
    ]
    original = deepcopy(report)
    result = render_html(report)
    parser = Elements()
    parser.feed(result)
    assert attack in "".join(parser.text)
    assert not any(tag in {"script", "img"} for tag, _ in parser.elements)
    assert "&lt;script&gt;" in result
    assert report == original


def test_raw_private_metadata_is_not_accidentally_serialized():
    report = sample_report()
    report["uid"] = "PRIVATE_UID"
    report["summary_text"] = "PRIVATE_TITLE"
    report["description"] = "PRIVATE_DESCRIPTION"
    report["sources"]["before"]["filename"] = "/private/PRIVATE_FILENAME.ics"
    result = render_html(report)
    assert "PRIVATE_" not in result
    assert "Raw UIDs, calendar text and source filenames are omitted" in result


def test_unknown_schema_or_kind_fails_instead_of_silently_dropping_differences():
    report = sample_report()
    report["schema_version"] = "future"
    with pytest.raises(ValueError, match="schema"):
        render_html(report)
    report["schema_version"] = "1.0"
    report["changes"] = [change("future_kind")]
    with pytest.raises(ValueError, match="omit"):
        render_html(report)


def test_synthetic_badge_requires_explicit_presentation_option():
    report = sample_report()
    assert "Synthetic example" not in render_html(report)
    result = render_html(report, synthetic=True)
    assert "Synthetic example / 人工示例" in result
    assert 'href="index.html"' in result
