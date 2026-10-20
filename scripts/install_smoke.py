"""Check the controller wheel and optional GUI in a clean environment."""

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
    if result.returncode:
        print(result.stdout + result.stderr)
        result.check_returncode()
    return result


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    stem = f"{project['name'].replace('-', '_')}-{project['version']}"
    wheel = ROOT / "dist" / f"{stem}-py3-none-any.whl"
    source = ROOT / "dist" / f"{stem}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        modules = {Path(name).name for name in archive.namelist() if name.endswith(".py")}
    expected = {path.name for path in (ROOT / "src/coherent_verdi").glob("*.py")}
    if modules != expected:
        raise RuntimeError(f"wheel modules differ from current source: {modules ^ expected}")
    with tarfile.open(source) as archive:
        members = {name.partition("/")[2] for name in archive.getnames()}
    required = {
        "scripts/install_smoke.py",
        "scripts/test_watchdog.cjs",
        "tests/conftest.py",
        "README.md",
        "verdi.manual_v5.pdf",
        "src/coherent_verdi/py.typed",
        "src/coherent_verdi/assets/watchdog.js",
    }
    required.update(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "examples").iterdir()
        if p.suffix in (".py", ".md")
    )
    required.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md"))
    if missing := required - members:
        raise RuntimeError(f"source distribution lacks supporting files: {sorted(missing)}")
    scratch = ROOT / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-smoke-", dir=scratch) as directory:
        env_path = Path(directory) / "env"
        venv.EnvBuilder(with_pip=True).create(env_path)
        executable = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "--cache-dir",
                str(scratch / "pip-cache"),
                str(wheel),
            ]
        )
        run([str(executable), "-m", "pip", "check"])
        # CWD outside source and isolated mode prove this imports the installed wheel.
        check = run(
            [
                str(executable),
                "-I",
                "-c",
                "import coherent_verdi, sys; from pathlib import Path; "
                "assert 'serial' not in sys.modules; assert 'dash' not in sys.modules; "
                "assert Path(coherent_verdi.__file__).parent.joinpath('py.typed').exists(); "
                "assets = Path(coherent_verdi.__file__).parent / 'assets'; "
                "assert assets.joinpath('style.css').exists(); "
                "assert assets.joinpath('watchdog.js').exists(); "
                "print(coherent_verdi.__file__)",
            ],
            cwd=directory,
        )
        run([str(executable), "-I", "-c", "import serial; assert serial.VERSION"], cwd=directory)
        cli = run([str(executable), "-I", "-m", "coherent_verdi", "status"], cwd=directory)
        data = json.loads(cli.stdout)
        assert data["simulated"] is True and data["power_w"] == 0.0
        watch = run(
            [str(executable), "-I", "-m", "coherent_verdi", "watch", "--count", "1"],
            cwd=directory,
        )
        assert json.loads(watch.stdout)["status"]["simulated"] is True
        # Exercise installed queries and commissioning without opening a device.
        serial_check = r"""
from unittest.mock import patch
import serial, sys
from coherent_verdi.__main__ import main
reply = iter(bytes([c]) for c in b'WHEEL-TEST-FIRMWARE\r\n')
with patch.object(serial, 'Serial') as factory:
    stream = factory.return_value
    stream.in_waiting = 0
    stream.write.side_effect = len
    stream.read.side_effect = lambda size: next(reply, b'')
    assert main(['--port', 'FAKE-ONLY', '--model', 'V5', *sys.argv[1:]]) == 0
    assert stream.port == 'FAKE-ONLY'
    stream.open.assert_called_once_with()
    stream.close.assert_called_once_with()
    stream.write.assert_called_once_with(b'?SV\r\n')
"""
        for command in (["query", "?SV"], ["commission"]):
            result = run([str(executable), "-I", "-c", serial_check, *command], cwd=directory)
            data = json.loads(result.stdout)
            if command == ["commission"]:
                assert data["payload"] == "WHEEL-TEST-FIRMWARE"
                assert data["outcome"] == "captured" and data["simulated"] is False
                assert bytes.fromhex(data["response_hex"]) == b"WHEEL-TEST-FIRMWARE\r\n"
            else:
                assert data == "WHEEL-TEST-FIRMWARE"
        # Hardware examples run only with substituted peers in the install check.
        example_check = r"""
import builtins, runpy, sys
from unittest.mock import patch
from coherent_verdi import SimulatedVerdi, VerdiController
sim = SimulatedVerdi('V5')
sim.set_key(True)
main = runpy.run_path(sys.argv[1])['main']
main.__globals__.update(PORT='FAKE-ONLY', MODEL='V5', BAUDRATE=19200,
    ACTIVE_FAULT_CLEAR_REPLY='SYSTEM OK', TARGET_W=0.25, POWER_LIMIT_W=0.5)
def confirm(prompt):
    return 'CONNECT' if 'CONNECT' in prompt else 'SET' if 'SET' in prompt else 'RUN'
with patch.object(VerdiController, '_open', lambda c: sim.connect()), \
     patch.object(VerdiController, '_close', lambda c: sim.disconnect()), \
     patch.object(VerdiController, '_exchange', lambda c, wire: sim._exchange(wire)), \
     patch.object(builtins, 'input', confirm):
    main()
assert sim.requests[0] == b'?SV\r\n'
"""
        for example in sorted((ROOT / "examples").glob("0*.py")):
            run([str(executable), "-I", "-c", example_check, str(example)], cwd=directory)
        entrypoint = env_path / ("Scripts/verdi.exe" if os.name == "nt" else "bin/verdi")
        result = json.loads(run([str(entrypoint), "query", "?SV"], cwd=directory).stdout)
        assert result == "SIMULATOR-0.1"
        missing_gui = subprocess.run(
            [str(executable), "-I", "-m", "coherent_verdi", "gui"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert missing_gui.returncode == 2
        assert json.loads(missing_gui.stderr)["type"] == "ModuleNotFoundError"
        print(f"PASS: isolated controller wheel, assets, CLI, examples; {check.stdout.strip()}")
        run(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "--cache-dir",
                str(scratch / "pip-cache"),
                f"{wheel}[gui]",
            ]
        )
        run([str(executable), "-m", "pip", "check"])
        smoke = run(
            [str(executable), "-I", str(Path(__file__).resolve()), "--gui-smoke"], cwd=directory
        )
        print(smoke.stdout.strip())


def gui_smoke() -> None:
    from importlib.metadata import version

    import serial
    import serial.tools.list_ports

    from coherent_verdi import (
        SimulatedVerdi,
    )
    from coherent_verdi.gui import Monitor, create_app

    def prohibited(*args: object, **kwargs: object) -> None:
        raise AssertionError("physical serial access/discovery prohibited in GUI smoke test")

    # Installed adapter dependencies must never turn this check into a hardware test.
    serial.Serial = prohibited
    serial.serial_for_url = prohibited
    serial.tools.list_ports.comports = prohibited
    serial.tools.list_ports.grep = prohibited
    sim = SimulatedVerdi("V5")
    with sim as controller:
        telemetry = Monitor(controller, history_size=2)
        app = create_app(telemetry)
        client = app.server.test_client()
        for path in ("/", "/_dash-layout", "/assets/style.css", "/assets/watchdog.js"):
            assert client.get(path).status_code == 200, path
        key = next(iter(app.callback_map))
        payload = {
            "output": key,
            "outputs": [
                {"id": item.component_id, "property": item.component_property}
                for item in app.callback_map[key]["output"]
            ],
            "inputs": [{"id": "refresh", "property": "n_intervals", "value": 1}],
            "changedPropIds": ["refresh.n_intervals"],
            "state": [],
        }

        def refresh(expected: str) -> dict:
            before = sim.requests
            response = client.post("/_dash-update-component", json=payload)
            assert response.status_code == 200, response.data
            data = response.get_json()["response"]
            assert data["health"]["children"] == expected, data
            assert sim.requests == before, "GUI callback must read only the cache"
            return data

        refresh("NO DATA")
        telemetry.poll_once()
        assert refresh("LIVE")["source"]["children"] == "SIMULATOR"
        sim.set_faults(5, 999)
        telemetry.poll_once()
        fault_view = refresh("LIVE")
        assert fault_view["laser"]["children"] == "FAULT"
        assert "999" in str(fault_view["instrument"])
        sim.inject_timeout()
        telemetry.poll_once()
        error_view = refresh("ERROR")
        assert error_view["laser"]["children"] == "UNKNOWN"
        assert error_view["power-graph"]["figure"]["data"][0]["y"][-1] is None
        telemetry.poll_once()
        refresh("ERROR")  # Failed sessions never recover implicitly.
        assert len(telemetry.snapshot()["history"]) == 2
    print(
        "PASS: installed GUI assets, NO DATA/LIVE/FAULT/ERROR callbacks, "
        "bounded cache, no callback acquisition; "
        f"Dash {version('dash')}, Plotly {version('plotly')}, pySerial {version('pyserial')}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui-smoke", action="store_true", help=argparse.SUPPRESS)
    if parser.parse_args().gui_smoke:
        gui_smoke()
    else:
        main()
