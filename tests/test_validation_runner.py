"""A failed validation attempt must invalidate any previous PASS checkpoint."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("test", 240),
        OSError("cannot start validator"),
        KeyboardInterrupt(),
    ],
)
def test_interrupted_validation_does_not_leave_stale_pass(tmp_path, monkeypatch, failure):
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate.py"
    spec = importlib.util.spec_from_file_location("validation_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    records = tmp_path / "records"
    records.mkdir()
    report_path = records / "validation.json"
    report_path.write_text('{"status":"PASS"}')
    monkeypatch.setattr(runner, "RECORDS", records)
    monkeypatch.setattr(runner, "fingerprint", lambda: {})

    def interrupt(*args, **kwargs):
        assert json.loads(report_path.read_text())["status"] == "RUNNING"
        raise failure

    monkeypatch.setattr(runner.subprocess, "run", interrupt)
    with pytest.raises(type(failure)):
        runner.main()
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAIL"
    assert report["physical_validation"] == "UNTESTED"
