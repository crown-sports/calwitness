import json

import pytest

from calwitness import compare_calendars


def event(*lines):
    return "BEGIN:VEVENT\nDTSTAMP:20260101T000000Z\n" + "\n".join(lines) + "\nEND:VEVENT\n"


def calendar(*events, extra=""):
    return (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//CalWitness tests//EN\n"
        + extra
        + "".join(events)
        + "END:VCALENDAR\n"
    ).encode()


def compare(a, b=None, **kwargs):
    return compare_calendars(
        a, a if b is None else b, start="2026-01-01", end="2027-01-01", **kwargs
    )


def single(start="20260329T120000Z", end="20260329T130000Z", uid="one"):
    return event(f"UID:{uid}", f"DTSTART:{start}", f"DTEND:{end}")


def test_empty_calendar_is_complete():
    result = compare(calendar())
    assert result["complete"] and result["status"] == "clean"
    assert result["summary"]["unchanged"] == 0


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("20260329T140000Z", "20260329T150000Z", "moved"),
        ("20260329T120000Z", "20260329T140000Z", "duration_changed"),
        ("20260329T140000Z", "20260329T160000Z", "moved_and_resized"),
    ],
)
def test_single_event_changes(start, end, expected):
    result = compare(calendar(single()), calendar(single(start, end)))
    assert result["status"] == "changed"
    assert result["changes"][0]["kind"] == expected
    assert result["changes"][0]["matching"] == "uid"


def test_uid_change_is_added_removed_not_fuzzy_matched():
    result = compare(calendar(single()), calendar(single(uid="different")))
    assert result["summary"]["added"] == result["summary"]["removed"] == 1
    assert result["summary"]["moved"] == 0


def test_equivalent_zone_notation_is_clean():
    before = calendar(single())
    after = calendar(
        event(
            "UID:one",
            "DTSTART;TZID=Europe/Berlin:20260329T140000",
            "DTEND;TZID=Europe/Berlin:20260329T150000",
        )
    )
    assert compare(before, after)["status"] == "clean"


def test_timezone_definition_is_not_shared_between_inputs():
    def source(offset):
        zone = (
            "BEGIN:VTIMEZONE\nTZID:Private/Example\nBEGIN:STANDARD\n"
            "DTSTART:19700101T000000\nTZOFFSETFROM:"
            + offset
            + "\nTZOFFSETTO:"
            + offset
            + "\nEND:STANDARD\nEND:VTIMEZONE\n"
        )
        return calendar(
            event(
                "UID:zone",
                "DTSTART;TZID=Private/Example:20260329T120000",
                "DTEND;TZID=Private/Example:20260329T130000",
            ),
            extra=zone,
        )

    result = compare(source("+0100"), source("+0200"))
    assert result["status"] == "changed", result["issues"]
    assert result["changes"][0]["kind"] == "moved"
    assert result["changes"][0]["before"]["start"] == "2026-03-29T11:00:00Z"
    assert result["changes"][0]["after"]["start"] == "2026-03-29T10:00:00Z"


def test_embedded_definition_overrides_known_iana_name():
    source = calendar(
        event("UID:zone", "DTSTART;TZID=Europe/Berlin:20260329T120000"),
        extra=(
            "BEGIN:VTIMEZONE\nTZID:Europe/Berlin\nBEGIN:STANDARD\nDTSTART:19700101T000000\n"
            "TZOFFSETFROM:+0500\nTZOFFSETTO:+0500\nEND:STANDARD\nEND:VTIMEZONE\n"
        ),
    )
    expected = calendar(event("UID:zone", "DTSTART:20260329T070000Z"))
    assert compare(source, expected)["status"] == "clean"


def test_rrule_exdate_rdate_and_lost_override():
    master = event(
        "UID:series",
        "DTSTART:20261020T100000Z",
        "DTEND:20261020T110000Z",
        "RRULE:FREQ=DAILY;COUNT=4",
        "EXDATE:20261021T100000Z",
        "RDATE:20261025T100000Z",
    )
    override = event(
        "UID:series",
        "RECURRENCE-ID:20261022T100000Z",
        "DTSTART:20261022T150000Z",
        "DTEND:20261022T160000Z",
    )
    result = compare(calendar(master, override), calendar(master))
    assert result["complete"], result["issues"]
    assert result["summary"]["unchanged"] == 3
    assert result["summary"]["moved"] == 1
    difference = result["changes"][0]
    assert difference["key"] == "2026-10-22T10:00:00Z"
    assert difference["before"]["override"] is True
    assert difference["after"]["override"] is False


def test_dropped_exdate_adds_occurrence():
    master = event("UID:series", "DTSTART:20261020T100000Z", "RRULE:FREQ=DAILY;COUNT=3")
    result = compare(
        calendar(master.replace("END:VEVENT", "EXDATE:20261021T100000Z\nEND:VEVENT")),
        calendar(master),
    )
    assert result["summary"]["added"] == 1
    assert result["changes"][0]["after"]["start"] == "2026-10-21T10:00:00Z"


def test_full_instant_identity_does_not_merge_two_occurrences_on_one_utc_day():
    master = event(
        "UID:dst", "DTSTART;TZID=Europe/Berlin:20260328T013000", "RRULE:FREQ=DAILY;COUNT=4"
    )
    before = calendar(master)
    after = calendar(
        master.replace("END:VEVENT", "EXDATE;TZID=Europe/Berlin:20260329T013000\nEND:VEVENT")
    )
    result = compare(before, after)
    assert result["complete"], result["issues"]
    assert result["summary"]["removed"] == 1 and result["summary"]["unchanged"] == 3
    assert result["changes"][0]["key"] == "2026-03-29T00:30:00Z"


def test_dst_local_series_vs_fixed_utc_is_detected_without_guessing_pairs():
    a = calendar(
        event("UID:dst", "DTSTART;TZID=Europe/Berlin:20260328T090000", "RRULE:FREQ=DAILY;COUNT=4")
    )
    b = calendar(event("UID:dst", "DTSTART:20260328T080000Z", "RRULE:FREQ=DAILY;COUNT=4"))
    result = compare(a, b)
    assert result["summary"]["unchanged"] == 1
    assert result["summary"]["added"] == result["summary"]["removed"] == 3
    assert result["summary"]["moved"] == 0


def test_equivalent_recurrence_timezone_notation():
    a = calendar(
        event(
            "UID:series", "DTSTART;TZID=Asia/Shanghai:20261020T180000", "RRULE:FREQ=DAILY;COUNT=3"
        )
    )
    b = calendar(event("UID:series", "DTSTART:20261020T100000Z", "RRULE:FREQ=DAILY;COUNT=3"))
    assert compare(a, b)["summary"]["unchanged"] == 3


def test_all_day_default_and_exclusive_end():
    a = calendar(event("UID:day", "DTSTART;VALUE=DATE:20261020"))
    b = calendar(event("UID:day", "DTSTART;VALUE=DATE:20261020", "DTEND;VALUE=DATE:20261021"))
    assert compare(a, b)["status"] == "clean"
    c = calendar(event("UID:day", "DTSTART;VALUE=DATE:20261020", "DTEND;VALUE=DATE:20261022"))
    result = compare(a, c)
    assert result["changes"][0]["kind"] == "duration_changed"
    assert result["changes"][0]["before"]["kind"] == "date"


def test_all_day_recurrence_exdate_rdate():
    a = calendar(
        event(
            "UID:days",
            "DTSTART;VALUE=DATE:20261020",
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE;VALUE=DATE:20261021",
            "RDATE;VALUE=DATE:20261025",
        )
    )
    assert compare(a)["summary"]["unchanged"] == 3


def test_floating_time_requires_explicit_zone_even_with_x_wr_timezone():
    a = calendar(
        event("UID:float", "DTSTART:20261020T100000"), extra="X-WR-TIMEZONE:Europe/Berlin\n"
    )
    assert compare(a)["issues"][0]["code"] == "FLOATING_TIME"
    b = calendar(event("UID:float", "DTSTART:20261020T080000Z"))
    assert compare(a, b, floating_zone="Europe/Berlin")["status"] == "clean"


def test_floating_recurrence_is_localized_before_dst_expansion():
    a = calendar(event("UID:float", "DTSTART:20260328T090000", "RRULE:FREQ=DAILY;COUNT=4"))
    b = calendar(
        event(
            "UID:float", "DTSTART;TZID=Europe/Berlin:20260328T090000", "RRULE:FREQ=DAILY;COUNT=4"
        )
    )
    assert compare(a, b, floating_zone="Europe/Berlin")["summary"]["unchanged"] == 4


def test_single_move_across_window_boundary():
    result = compare_calendars(
        calendar(single()),
        calendar(single("20270102T100000Z", "20270102T110000Z")),
        start="2026-01-01",
        end="2027-01-01",
    )
    assert result["changes"][0]["kind"] == "moved"


def test_override_moved_out_of_window_retains_identity():
    master = event("UID:s", "DTSTART:20261020T100000Z", "RRULE:FREQ=DAILY;COUNT=2")
    override = event("UID:s", "RECURRENCE-ID:20261021T100000Z", "DTSTART:20270102T100000Z")
    result = compare(calendar(master), calendar(master, override))
    assert result["summary"]["moved"] == 1, result


@pytest.mark.parametrize("original", ["20261001T100000Z", "20261030T100000Z"])
@pytest.mark.parametrize("reverse", [False, True])
def test_override_far_original_key_outside_window(original, reverse):
    master = event("UID:s", "DTSTART:20261001T100000Z", "RRULE:FREQ=DAILY;COUNT=30")
    override = event("UID:s", "RECURRENCE-ID:" + original, "DTSTART:20261020T150000Z")
    inputs = (calendar(master), calendar(master, override))
    result = compare_calendars(
        *inputs[:: -1 if reverse else 1], start="2026-10-20", end="2026-10-21"
    )
    assert result["complete"], result["issues"]
    assert result["summary"]["moved"] == 1
    assert result["summary"]["added"] == result["summary"]["removed"] == 0
    assert result["summary"]["unchanged"] == 1


def test_focused_lookup_does_not_resurrect_excluded_original():
    master = event(
        "UID:s", "DTSTART:20261001T100000Z", "RRULE:FREQ=DAILY;COUNT=30", "EXDATE:20261001T100000Z"
    )
    override = event("UID:s", "RECURRENCE-ID:20261001T100000Z", "DTSTART:20261020T150000Z")
    result = compare_calendars(
        calendar(master), calendar(master, override), start="2026-10-20", end="2026-10-21"
    )
    assert result["summary"]["added"] == 1
    assert result["summary"]["moved"] == 0


@pytest.mark.parametrize(
    ("start", "duration", "expected"),
    [
        ("20260329T013000", "PT2H", "20260329T023000Z"),
        ("20260328T120000", "P1D", "20260329T100000Z"),
        ("20260328T120000", "PT24H", "20260329T110000Z"),
        ("20260328T120000", "P1DT2H", "20260329T120000Z"),
        ("20261025T013000", "PT2H", "20261025T013000Z"),
        ("20261024T120000", "P1D", "20261025T110000Z"),
        ("20261024T120000", "PT24H", "20261025T100000Z"),
    ],
)
def test_nominal_days_and_elapsed_duration_across_dst(start, duration, expected):
    original = event("UID:d", "DTSTART;TZID=Europe/Berlin:" + start)
    a = calendar(original.replace("END:VEVENT", "DURATION:" + duration + "\nEND:VEVENT"))
    b = calendar(original.replace("END:VEVENT", "DTEND:" + expected + "\nEND:VEVENT"))
    result = compare(a, b)
    assert result["status"] == "clean", result


@pytest.mark.parametrize(
    "end_definition", ["DURATION:PT2H", "DTEND;TZID=Europe/Berlin:20260328T033000"]
)
def test_recurring_exact_duration_crossing_dst(end_definition):
    a = calendar(
        event(
            "UID:d",
            "DTSTART;TZID=Europe/Berlin:20260328T013000",
            end_definition,
            "RRULE:FREQ=DAILY;COUNT=2",
        )
    )
    result = compare(a, calendar())
    second = next(c["before"] for c in result["changes"] if c["key"] == "2026-03-29T00:30:00Z")
    assert second["end"] == "2026-03-29T02:30:00Z"


def test_recurring_nominal_day_has_variable_elapsed_duration():
    a = calendar(
        event(
            "UID:d",
            "DTSTART;TZID=Europe/Berlin:20260328T120000",
            "DURATION:P1D",
            "RRULE:FREQ=DAILY;COUNT=2",
        )
    )
    result = compare(a, calendar())
    first = next(c["before"] for c in result["changes"] if c["key"] == "2026-03-28T11:00:00Z")
    assert first["end"] == "2026-03-29T10:00:00Z"


@pytest.mark.parametrize("start", ["20260328T023000", "20261024T023000"])
def test_nominal_duration_end_at_gap_or_fold_is_incomplete(start):
    a = calendar(event("UID:d", "DTSTART;TZID=Europe/Berlin:" + start, "DURATION:P1D"))
    result = compare(a)
    assert result["status"] == "incomplete"
    assert result["issues"][0]["code"] == "AMBIGUOUS_LOCAL_TIME"


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=DAILY;BYMONTHDAY=0",
        "FREQ=DAILY;BYMONTH=13",
        "FREQ=DAILY;BYMONTH=-1",
        "FREQ=MONTHLY;BYMONTHDAY=32",
        "FREQ=YEARLY;BYYEARDAY=367",
        "FREQ=YEARLY;BYWEEKNO=54",
        "FREQ=YEARLY;BYSETPOS=0;BYDAY=MO",
        "FREQ=DAILY;BYDAY=1MO",
        "FREQ=MONTHLY;BYDAY=0MO",
        "FREQ=MONTHLY;BYDAY=54MO",
        "FREQ=WEEKLY;BYMONTHDAY=1",
        "FREQ=DAILY;BYYEARDAY=1",
        "FREQ=MONTHLY;BYWEEKNO=1",
        "FREQ=YEARLY;BYDAY=1MO;BYWEEKNO=1",
        "FREQ=DAILY;BYSETPOS=1",
        "FREQ=DAILY;WKST=BAD",
    ],
)
def test_invalid_rule_selectors_never_look_clean(rule):
    a = calendar(event("UID:s", "DTSTART:20260115T100000Z", "RRULE:" + rule))
    result = compare(a)
    assert result["status"] == "incomplete"
    assert result["issues"][0]["code"] == "INVALID_RULE"


def test_tzid_on_utc_time_is_rejected_before_reinterpretation():
    a = calendar(event("UID:s", "DTSTART;TZID=Europe/Berlin:20260115T100000Z"))
    result = compare(a)
    assert result["issues"][0]["code"] == "INVALID_DATE"


@pytest.mark.parametrize("version", [b"VERSION:3.0", b"VERSION:1.0", b""])
def test_calendar_version_must_be_supported(version):
    data = calendar(single()).replace(b"VERSION:2.0", version)
    assert compare(data)["issues"][0]["code"] == "UNSUPPORTED_VERSION"


@pytest.mark.parametrize(
    ("start", "rule"),
    [
        ("DTSTART;VALUE=DATE:20261020", "FREQ=DAILY;BYHOUR=10"),
        ("DTSTART;VALUE=DATE:20261020", "FREQ=DAILY;UNTIL=20261022T100000Z"),
        ("DTSTART:20261020T100000Z", "FREQ=DAILY;UNTIL=20261022"),
        ("DTSTART;TZID=Europe/Berlin:20261020T100000", "FREQ=DAILY;UNTIL=20261022T100000"),
    ],
)
def test_until_and_rule_value_types_are_not_silently_coerced(start, rule):
    data = calendar(event("UID:until", start, "RRULE:" + rule))
    assert compare(data)["issues"][0]["code"] == "INVALID_RULE"


def test_floating_until_uses_explicit_zone_consistently():
    a = calendar(
        event("UID:until", "DTSTART:20261020T100000", "RRULE:FREQ=DAILY;UNTIL=20261022T100000")
    )
    b = calendar(
        event("UID:until", "DTSTART:20261020T080000Z", "RRULE:FREQ=DAILY;UNTIL=20261022T080000Z")
    )
    result = compare(a, b, floating_zone="Europe/Berlin")
    assert result["status"] == "clean" and result["summary"]["unchanged"] == 3


def test_window_excludes_end_includes_start_and_no_overlap_only_event():
    a = calendar(
        single("20251231T100000Z", "20260102T100000Z", "overlap"),
        single("20260101T000000Z", "20260101T010000Z", "start"),
        single("20270101T000000Z", "20270101T010000Z", "end"),
    )
    assert compare(a)["summary"]["unchanged"] == 1


def test_cancellation_removes_occurrence():
    master = event("UID:s", "DTSTART:20261020T100000Z", "RRULE:FREQ=DAILY;COUNT=2")
    cancelled = event(
        "UID:s", "RECURRENCE-ID:20261021T100000Z", "DTSTART:20261021T100000Z", "STATUS:CANCELLED"
    )
    result = compare(calendar(master), calendar(master, cancelled))
    assert result["summary"]["removed"] == 1


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (calendar(event("DTSTART:20261020T100000Z")), "MISSING_UID"),
        (calendar(event("UID:a")), "MISSING_START"),
        (calendar(single(), single()), "DUPLICATE_IDENTITY"),
        (calendar(single(), single("20261020T100000Z", "20261020T110000Z")), "AMBIGUOUS_IDENTITY"),
        (
            calendar(event("UID:a", "DTSTART:20261020T100000Z", "RECURRENCE-ID:20261020T090000Z")),
            "ORPHAN_OVERRIDE",
        ),
        (calendar(event("UID:a", "DTSTART;TZID=Not/AZone:20261020T100000")), "UNKNOWN_TIMEZONE"),
        (
            calendar(event("UID:a", "DTSTART:20261020T100000Z", "RRULE:FREQ=SECONDLY")),
            "UNSUPPORTED_RULE",
        ),
        (
            calendar(
                event("UID:a", "DTSTART:20261020T100000Z", "RRULE:FREQ=DAILY;RSCALE=CHINESE")
            ),
            "UNSUPPORTED_RULE",
        ),
        (
            calendar(event("UID:a", "DTSTART:20261020T100000Z", "EXDATE;VALUE=DATE:20261021")),
            "DATE_TYPE_MISMATCH",
        ),
        (
            calendar(
                event(
                    "UID:a", "DTSTART:20261020T100000Z", "RDATE;VALUE=PERIOD:20261021T100000Z/PT1H"
                )
            ),
            "UNSUPPORTED_DATE",
        ),
        (
            calendar(event("UID:a", "DTSTART;TZID=Europe/Berlin:20261025T023000")),
            "AMBIGUOUS_LOCAL_TIME",
        ),
        (
            calendar(event("UID:a", "DTSTART;TZID=Europe/Berlin:20260329T023000")),
            "AMBIGUOUS_LOCAL_TIME",
        ),
        (
            calendar(
                event(
                    "UID:a",
                    "DTSTART:20261020T100000Z",
                    "RECURRENCE-ID;RANGE=THISANDFUTURE:20261020T100000Z",
                )
            ),
            "UNSUPPORTED_RANGE",
        ),
        (
            calendar(event("UID:a", "DTSTART:20261020T100000Z", "DTEND:20261020T090000Z")),
            "INVALID_EVENT",
        ),
        (b"not a calendar", "PARSE_ERROR"),
    ],
)
def test_incomplete_never_looks_clean_or_invents_missing_events(source, code):
    result = compare(source, calendar(single()))
    assert result["status"] == "incomplete" and result["complete"] is False
    assert result["issues"][0]["code"] == code, result["issues"]
    assert result["changes"] == []


def test_dense_rule_rejected_before_engine(monkeypatch):
    import icalendar

    from calwitness import worker

    monkeypatch.setattr(icalendar.Calendar, "from_ical", lambda _: pytest.fail("parser called"))
    data = calendar(event("UID:a", "DTSTART:20261020T100000Z", "RRULE:FREQ=SECONDLY"))
    with pytest.raises(worker.Unsupported) as error:
        worker.process(data, {})
    assert error.value.code == "UNSUPPORTED_RULE"


def test_dense_daily_rule_budget():
    data = calendar(event("UID:a", "DTSTART:20260101T100000Z", "RRULE:FREQ=DAILY"))
    assert compare(data, max_occurrences=10)["issues"][0]["code"] == "EXPANSION_LIMIT"


def test_nonexistent_generated_time_is_incomplete_not_silently_miscounted():
    data = calendar(
        event("UID:a", "DTSTART;TZID=Europe/Berlin:20260328T023000", "RRULE:FREQ=DAILY;COUNT=3")
    )
    result = compare(data)
    assert result["status"] == "incomplete"
    assert result["issues"][0]["code"] == "AMBIGUOUS_LOCAL_TIME"
    assert result["changes"] == []


def test_payload_free_report_on_success_and_failure():
    secret = "PRIVATE-title-attendee-description-UID"
    data = calendar(
        event(
            "UID:" + secret,
            "SUMMARY:" + secret,
            "DESCRIPTION:" + secret,
            "ATTENDEE:mailto:" + secret,
            "DTSTART:20261020T100000Z",
        )
    )
    assert secret not in json.dumps(compare(data, calendar()))
    assert secret not in json.dumps(compare(data + secret.encode()))


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-01-01", "2026-01-01"),
        ("2026-01-02", "2026-01-01"),
        ("20260101", "2026-01-02"),
        ("2026-01-01", "2040-01-01"),
    ],
)
def test_invalid_window(start, end):
    with pytest.raises(ValueError):
        compare_calendars(calendar(), calendar(), start=start, end=end)
