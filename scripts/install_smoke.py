"""Exercise built distributions in one clean environment, first core then GUI/serial extras."""

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
    if result.returncode:
        print(result.stdout + result.stderr)
        result.check_returncode()
    return result


def main() -> None:
    wheels = sorted((ROOT / "dist").glob("coherent_verdi_control-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("build one unambiguous current wheel into dist/ first")
    sources = sorted((ROOT / "dist").glob("coherent_verdi_control-*.tar.gz"))
    if len(sources) != 1:
        raise RuntimeError("build one unambiguous current sdist into dist/ first")
    with tarfile.open(sources[0]) as archive:
        members = {name.partition("/")[2] for name in archive.getnames()}
    required = {
        "scripts/validate.py",
        "scripts/install_smoke.py",
        "scripts/test_watchdog.cjs",
        "examples/simulated_session.py",
        "examples/async_integration.py",
        "tests/test_validation_runner.py",
        "src/coherent_verdi/py.typed",
        "src/coherent_verdi/assets/watchdog.js",
    }
    required.update(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "examples" / "tutorials").iterdir()
        if p.suffix in (".py", ".ipynb", ".md")
    )
    if missing := required - members:
        raise RuntimeError(f"source distribution lacks supporting files: {sorted(missing)}")
    scratch = ROOT / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-smoke-", dir=scratch) as directory:
        env_path = Path(directory) / "env"
        venv.EnvBuilder(with_pip=True).create(env_path)
        executable = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(executable), "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0])])
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
        cli = run(
            [str(executable), "-I", "-m", "coherent_verdi", "--demo", "status"], cwd=directory
        )
        data = json.loads(cli.stdout)
        assert data["simulated"] is True and data["result"]["power_w"] == 1.0
        for example in ("simulated_session.py", "async_integration.py"):
            run([str(executable), "-I", str(ROOT / "examples" / example)], cwd=directory)
        for example in sorted((ROOT / "examples" / "tutorials").glob("*.py")):
            run([str(executable), "-I", str(example)], cwd=directory)
        entrypoint = env_path / ("Scripts/verdi.exe" if os.name == "nt" else "bin/verdi")
        result = json.loads(run([str(entrypoint), "query", "?SV"], cwd=directory).stdout)
        assert result["result"] == "SIMULATOR-0.1"
        missing_gui = subprocess.run(
            [str(executable), "-I", "-m", "coherent_verdi", "gui"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert missing_gui.returncode == 2
        assert json.loads(missing_gui.stderr)["type"] == "ModuleNotFoundError"
        print(f"PASS: isolated core wheel, assets, CLI, examples; {check.stdout.strip()}")
        run([str(executable), "-m", "pip", "install", f"{wheels[0]}[serial,gui]"])
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
        ControllerConfig,
        Model,
        SimulatedTransport,
        TelemetryService,
        VerdiController,
    )
    from coherent_verdi.gui import create_app

    def prohibited(*args: object, **kwargs: object) -> None:
        raise AssertionError("physical serial access/discovery prohibited in GUI smoke test")

    # Installed adapter dependencies must never turn this check into a hardware test.
    serial.Serial = prohibited
    serial.serial_for_url = prohibited
    serial.tools.list_ports.comports = prohibited
    serial.tools.list_ports.grep = prohibited
    sim = SimulatedTransport(Model.V5)
    with VerdiController(sim, ControllerConfig(Model.V5)) as controller:
        telemetry = TelemetryService(controller, history_size=2)
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
        refresh("LIVE")
        assert len(telemetry.history) == 2
        assert not telemetry.running
    print(
        "PASS: installed GUI assets, NO DATA/LIVE/FAULT/ERROR/recovery callbacks, "
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
