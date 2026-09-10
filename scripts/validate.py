"""Reproducible, fail-fast, hardware-free candidate validation and fingerprinting."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "records"


def fingerprint() -> dict[str, str]:
    paths = [
        ROOT / name
        for name in (
            "pyproject.toml",
            "MANIFEST.in",
            "README.md",
            "PROJECT.md",
            "AGENTS.md",
            "ARCHITECTURE.md",
            "HARDWARE_VALIDATION.md",
            ".gitignore",
            ".gitattributes",
            "records/FRAMEWORK.md",
            "records/requirements-validated.txt",
        )
    ]
    for directory in ("src/coherent_verdi", "tests", "scripts", "examples", "docs", ".github"):
        paths.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def validate() -> int:
    RECORDS.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    commands = [
        (
            "TEST-002..006/009",
            [
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--cov=coherent_verdi",
                "--cov-report=term-missing",
                "--junitxml=records/junit.xml",
            ],
        ),
        ("TEST-007 lint", ["-m", "ruff", "check", "."]),
        ("TEST-007 format", ["-m", "ruff", "format", "--check", "."]),
        ("TEST-007 typing", ["-m", "mypy"]),
        ("TEST-007 dependencies", ["-m", "pip", "check"]),
        ("TEST-007 build", ["-m", "build", "--no-isolation"]),
        ("TEST-007 CLI", ["-m", "coherent_verdi", "--demo", "status"]),
        ("TEST-007 example", ["examples/simulated_session.py"]),
        ("TEST-007 async", ["examples/async_integration.py"]),
        ("TEST-007 install", ["scripts/install_smoke.py"]),
    ]
    commands = [(test_id, [sys.executable, *args]) for test_id, args in commands]
    commands.append(
        ("TEST-006 watchdog", [environment.get("VERDI_NODE", "node"), "scripts/test_watchdog.cjs"])
    )
    before = fingerprint()
    results = []
    with (RECORDS / "validation.log").open("w", encoding="utf-8") as log:
        for test_id, command in commands:
            runtime = "python" if command[0] == sys.executable else "node"
            label = runtime + " " + " ".join(command[1:])
            print(f"Running {label}", flush=True)
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=240,
            )
            log.write(f"\n{test_id}: {label}\n{completed.stdout}\nexit={completed.returncode}\n")
            log.flush()
            results.append({"test": test_id, "command": label, "exit_code": completed.returncode})
            if completed.returncode:
                print(completed.stdout, flush=True)
                break
    after = fingerprint()
    manifest_sha = hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()
    preserved = {
        "verdi.manual_v5.pdf": "d4a7a8a2a1e0c678bb00a5fd70be6ea1d649be063ab752de485a59daa3103f73",
        "AGENTS.md": "800197bfb6731da6b8fa5d0412300401a5012a2b99967e6bbe8b73b8830af32e",
        "ARCHITECTURE.md": "52b9d65e211f0471bb116a3c7dbc96512c44d17c505e78dff38ba478c2a02b4f",
    }
    inputs_ok = all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha for p, sha in preserved.items()
    )
    # This original user reference stays local and is not required in clean clones.
    prompt_log = ROOT / "prompt log.txt"
    local_reference_ok = not prompt_log.exists() or hashlib.sha256(
        prompt_log.read_bytes()
    ).hexdigest() == ("51b5d310a26027a5a6ec25b0b9416cc1818b2880939c7ab555ef594838a8ba45")
    passed = (
        len(results) == len(commands)
        and all(r["exit_code"] == 0 for r in results)
        and before == after
        and inputs_ok
        and local_reference_ok
    )
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "scope": "software and simulator only",
        "physical_validation": "UNTESTED",
        "python": sys.version,
        "platform": platform.platform(),
        "candidate_sha256": manifest_sha,
        "candidate_files": after,
        "source_unchanged_during_validation": before == after,
        "preserved_inputs_match": inputs_ok,
        "local_prompt_log_present": prompt_log.exists(),
        "local_prompt_log_match_if_present": local_reference_ok,
        "dependencies": {d.metadata["Name"]: d.version for d in distributions()},
        "results": results,
        "build_artifacts": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "dist").glob("*")
            if p.is_file()
        },
    }
    (RECORDS / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: candidate {manifest_sha}")
    return 0 if passed else 1


def main() -> int:
    RECORDS.mkdir(exist_ok=True)
    report_path = RECORDS / "validation.json"
    checkpoint = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "status": "RUNNING",
        "scope": "software and simulator only",
        "physical_validation": "UNTESTED",
    }
    report_path.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
    try:
        return validate()
    except BaseException as exc:
        # A timeout, interruption or missing build directory must not leave the
        # previous candidate's PASS masquerading as the result of this invocation.
        checkpoint.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        report_path.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
