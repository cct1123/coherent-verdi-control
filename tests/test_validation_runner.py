"""A failed validation attempt must invalidate any previous PASS checkpoint."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def validation_runner(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate.py"
    spec = importlib.util.spec_from_file_location("validation_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    records = tmp_path / "records"
    records.mkdir()
    monkeypatch.setattr(runner, "RECORDS", records)
    monkeypatch.setattr(runner, "fingerprint", lambda: {})
    return runner


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("test", 240),
        OSError("cannot start validator"),
        KeyboardInterrupt(),
    ],
)
def test_interrupted_validation_does_not_leave_stale_pass(validation_runner, monkeypatch, failure):
    runner = validation_runner
    report_path = runner.RECORDS / "validation.json"
    report_path.write_text('{"status":"PASS"}')

    def interrupt(*args, **kwargs):
        assert json.loads(report_path.read_text())["status"] == "RUNNING"
        raise failure

    monkeypatch.setattr(runner.subprocess, "run", interrupt)
    with pytest.raises(type(failure)):
        runner.main()
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAIL"
    assert report["physical_validation"] == "UNTESTED"


def test_watchdog_failure_prevents_integrated_pass(validation_runner, monkeypatch):
    runner = validation_runner
    calls = []

    def completed(command, **kwargs):
        calls.append(command)
        code = 1 if command[-1] == "scripts/test_watchdog.cjs" else 0
        return subprocess.CompletedProcess(command, code, "injected watchdog result")

    monkeypatch.setattr(runner.subprocess, "run", completed)
    assert runner.main() == 1
    assert any(command[-1] == "scripts/test_watchdog.cjs" for command in calls)
    report = json.loads((runner.RECORDS / "validation.json").read_text())
    assert report["status"] == "FAIL"
    assert report["physical_validation"] == "UNTESTED"
    assert report["results"][-1]["exit_code"] == 1
