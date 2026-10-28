# Changelog

## 0.1.0

- Compare bounded VEVENT occurrence sets from two offline iCalendar snapshots.
- Match full original recurrence instants, including explicit moved overrides
  whose original keys lie outside the selected window.
- Explain additions, removals, moves and duration changes, with input checksums,
  component positions and pinned parser/timezone provenance.
- Respect all-day exclusive ends, embedded VTIMEZONE, explicit floating zones,
  and nominal-day versus elapsed-time duration semantics.
- Report unsupported, ambiguous and resource-limited input as incomplete.
- Include text/JSON/HTML output, synthetic red/green/incomplete examples and tests.
- Implementation and documentation assisted by OpenAI Codex (GPT-6), with
  independent agent review and executable regression tests.
