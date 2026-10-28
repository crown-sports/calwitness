import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from calwitness import compare_calendars
from calwitness.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
WINDOW = ["--from", "2026-10-01", "--until", "2026-11-01"]


@pytest.mark.parametrize(
    ("name", "code", "status"),
    [
        ("equivalent.ics", 0, "clean"),
        ("after.ics", 1, "changed"),
        ("duplicate.ics", 2, "incomplete"),
    ],
)
def test_installed_cli_json_exit_status_and_no_payload(name, code, status, tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "calwitness",
            "compare",
            str(EXAMPLES / "before.ics"),
            str(EXAMPLES / name),
            *WINDOW,
            "--json",
            "-",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == code, proc.stderr
    assert proc.stderr == ""
    assert "@example.invalid" not in proc.stdout
    assert json.loads(proc.stdout)["status"] == status


def test_write_json_html_and_leave_inputs_unchanged(tmp_path, capsys):
    source = EXAMPLES / "before.ics"
    saved = source.read_bytes()
    out_json, out_html = tmp_path / "report.json", tmp_path / "report.html"
    result = main(
        [
            "compare",
            str(source),
            str(EXAMPLES / "after.ics"),
            *WINDOW,
            "--json",
            str(out_json),
            "--html",
            str(out_html),
        ]
    )
    assert result == 1
    assert json.loads(out_json.read_text())["summary"]["moved"] == 1
    assert "<!doctype html>" in out_html.read_text().lower()
    assert source.read_bytes() == saved
    assert "CHANGED" in capsys.readouterr().out


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_output_cannot_alias_input(tmp_path, alias):
    path = tmp_path / "input.ics"
    path.write_bytes((EXAMPLES / "before.ics").read_bytes())
    target = tmp_path / "report.json"
    try:
        if alias == "direct":
            target = path
        elif alias == "symlink":
            target.symlink_to(path)
        else:
            target.hardlink_to(path)
    except OSError:
        pytest.skip("Filesystem does not permit this link type")
    original = path.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["compare", str(path), str(path), *WINDOW, "--json", str(target)])
    assert exc.value.code == 2 and path.read_bytes() == original


def test_missing_input_and_unwritable_output_return_2(tmp_path, capsys):
    assert main(["compare", str(tmp_path / "missing"), str(EXAMPLES / "before.ics"), *WINDOW]) == 2
    assert "No successful comparison" in capsys.readouterr().err
    assert (
        main(
            [
                "compare",
                str(EXAMPLES / "before.ics"),
                str(EXAMPLES / "equivalent.ics"),
                *WINDOW,
                "--json",
                str(tmp_path / "missing-parent" / "out.json"),
            ]
        )
        == 2
    )


def test_worker_timeout_is_incomplete_without_leaking_exception(monkeypatch):
    module = importlib.import_module("calwitness.compare")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("SECRET", 1, output="SECRET", stderr="SECRET")

    monkeypatch.setattr(module.subprocess, "run", timeout)
    result = compare_calendars(b"", b"", start="2026-10-01", end="2026-11-01")
    assert result["status"] == "incomplete"
    assert result["issues"][0]["code"] == "WORKER_TIMEOUT"
    assert "SECRET" not in json.dumps(result)


def test_worker_crash_and_invalid_json_are_incomplete(monkeypatch):
    module = importlib.import_module("calwitness.compare")
    for returned in (
        subprocess.CompletedProcess([], 1, "", "SECRET"),
        subprocess.CompletedProcess([], 0, "not json", ""),
    ):
        monkeypatch.setattr(module.subprocess, "run", lambda *a, returned=returned, **k: returned)
        result = compare_calendars(b"", b"", start="2026-10-01", end="2026-11-01")
        assert result["issues"][0]["code"] == "WORKER_FAILED"
        assert result["status"] == "incomplete"


def test_input_size_limit_precedes_worker(monkeypatch):
    module = importlib.import_module("calwitness.compare")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("worker called"))
    data = b"x" * (module.MAX_BYTES + 1)
    result = compare_calendars(data, data, start="2026-10-01", end="2026-11-01")
    assert result["issues"][0]["code"] == "INPUT_LIMIT"


def test_current_directory_cannot_shadow_parser_imports(tmp_path):
    (tmp_path / "icalendar.py").write_text("raise RuntimeError('SHADOWED')")
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "calwitness",
            "compare",
            str(EXAMPLES / "before.ics"),
            str(EXAMPLES / "equivalent.ics"),
            *WINDOW,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
