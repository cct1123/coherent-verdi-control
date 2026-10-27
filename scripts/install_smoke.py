"""Check the controller wheel and optional GUI in a clean environment."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `uv run` exports the running uv binary; fall back to PATH for direct invocation.
UV = os.environ.get("UV") or shutil.which("uv") or "uv"


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
        "tests/data/verdi_v2_status.json",
        "README.md",
        "examples/README.md",
        "verdi.manual_v5.pdf",
        "src/coherent_verdi/py.typed",
        "src/coherent_verdi/assets/watchdog.js",
        "src/coherent_verdi/assets/panel.js",
        "src/coherent_verdi/assets/bootstrap.min.css",
    }
    required.update(
        p.relative_to(ROOT).as_posix() for p in (ROOT / "examples").glob("0[0-6]_*.ipynb")
    )
    required.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md"))
    if missing := required - members:
        raise RuntimeError(f"source distribution lacks supporting files: {sorted(missing)}")
    with tempfile.TemporaryDirectory(prefix="verdi-install-smoke-") as directory:
        env_path = Path(directory) / "env"
        run([UV, "venv", "--quiet", "--python", sys.executable, str(env_path)])
        executable = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = [UV, "pip", "install", "--quiet", "--python", str(executable)]
        # A unique local path selects this build and also works with UV_OFFLINE=1.
        # --refresh-package conflicts with offline mode, even for a local wheel.
        fresh_wheel = Path(directory) / wheel.name
        shutil.copyfile(wheel, fresh_wheel)
        run([*install, str(fresh_wheel)])
        run([UV, "pip", "check", "--python", str(executable)])
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
                "assert assets.joinpath('panel.js').exists(); "
                "print(coherent_verdi.__file__)",
            ],
            cwd=directory,
        )
        run([str(executable), "-I", "-c", "import serial; assert serial.VERSION"], cwd=directory)
        api_check = """
from coherent_verdi import SimulatedVerdi, VerdiController
for cls in (VerdiController, SimulatedVerdi):
    assert callable(cls.read) and callable(cls.write)
    assert not hasattr(cls, 'get') and not hasattr(cls, 'set')
    assert not hasattr(cls, '_request')
with SimulatedVerdi(allow_writes=True, power_limit_w=0.5) as laser:
    assert laser.read(b'?SV') == b'SIMULATOR'
    assert laser.write(b'P=0.25') == b'\\r\\n'
    assert laser.get_value('?SP') == 0.25
    laser.set_value('P=0.2')
    assert laser.last_transaction['outcome'] == 'acknowledged'
    assert laser.get_value('?SP') == 0.2
    laser.set_power_w(0.1)
    assert laser.get_value('?SP') == 0.1
"""
        run([str(executable), "-I", "-c", api_check], cwd=directory)
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
with patch.object(serial, 'Serial') as factory:
    stream = factory.return_value
    stream.write.side_effect = len
    stream.read_until.return_value = b'WHEEL-TEST-FIRMWARE\r\n'
    assert main(['--no-prompt', '--port', 'FAKE-ONLY', '--model', 'V5', *sys.argv[1:]]) == 0
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
                assert data["outcome"] == "captured"
                assert bytes.fromhex(data["response_hex"]) == b"WHEEL-TEST-FIRMWARE\r\n"
            else:
                assert data == "WHEEL-TEST-FIRMWARE"
        # Hardware notebooks run only with substituted peers in the install check.
        example_check = r"""
import builtins, json, sys
from pathlib import Path
from unittest.mock import patch
import serial.tools.list_ports
from coherent_verdi import SimulatedVerdi, VerdiController
sim = SimulatedVerdi('V5', prompt=True)
sim.set_key(True)
requests = []
settings = dict(PORT='FAKE-ONLY', MODEL='V5', BAUDRATE=19200,
    ACTIVE_FAULT_CLEAR_REPLY=(b'SYSTEM OK' if Path(sys.argv[1]).name.startswith(('05_', '06_'))
        else 'SYSTEM OK'), TARGET_W=0.25, POWER_LIMIT_W=0.5)
cells = json.load(open(sys.argv[1], encoding='utf-8'))['cells']

class NotebookPeer:
    pending = b""
    def open(self):
        sim.connect()
    def close(self):
        sim.disconnect()
    def write(self, request):
        requests.append(request)
        self.pending += sim._simulate_response(request)
        return len(request)
    def read_until(self, expected=b"\n", size=None):
        end = self.pending.find(expected)
        count = len(self.pending) if end < 0 else end + len(expected)
        if size is not None:
            count = min(count, size)
        result, self.pending = self.pending[:count], self.pending[count:]
        return result
    def reset_output_buffer(self):
        pass
    def reset_input_buffer(self):
        self.pending = b""

namespace = {}
with patch.object(serial, 'Serial', lambda **kwargs: NotebookPeer()), \
     patch.object(serial.tools.list_ports, 'comports', lambda: []), \
     patch.object(builtins, 'input', lambda p: 'RUN' if 'RUN' in p else 'SET'):
    for cell in (c for c in cells if c['cell_type'] == 'code'):
        exec(''.join(cell['source']), namespace)
        if 'parameters' in cell['metadata'].get('tags', ()):
            namespace.update(settings)
# Device discovery only lists ports; every other lesson starts with ?SV.
discovery = Path(sys.argv[1]).name.startswith('00_')
assert requests == [] if discovery else requests[0] == b'?SV\r\n'
"""
        for example in sorted((ROOT / "examples").glob("0*.ipynb")):
            run([str(executable), "-I", "-c", example_check, str(example)], cwd=directory)
        entrypoint = env_path / ("Scripts/verdi.exe" if os.name == "nt" else "bin/verdi")
        result = json.loads(run([str(entrypoint), "query", "?SV"], cwd=directory).stdout)
        assert result == "SIMULATOR"
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
        run([*install, f"{fresh_wheel}[gui]"])
        run([UV, "pip", "check", "--python", str(executable)])
        smoke = run(
            [str(executable), "-I", str(Path(__file__).resolve()), "--gui-smoke"], cwd=directory
        )
        print(smoke.stdout.strip())


def gui_smoke() -> None:
    from importlib.metadata import version

    import serial
    import serial.tools.list_ports

    from coherent_verdi import SimulatedVerdi
    from coherent_verdi.gui import GuiSession, create_app
    from coherent_verdi.monitor import Monitor

    def prohibited(*args: object, **kwargs: object) -> None:
        raise AssertionError("physical serial access/discovery prohibited in GUI smoke test")

    # Installed adapter dependencies must never turn this check into a hardware test.
    serial.Serial = prohibited
    serial.serial_for_url = prohibited
    serial.tools.list_ports.comports = prohibited
    serial.tools.list_ports.grep = prohibited
    sim = SimulatedVerdi("V5")
    requests = []
    original_exchange = sim._simulate_response

    def exchange(request: bytes) -> bytes:
        requests.append(request)
        return original_exchange(request)

    sim._simulate_response = exchange
    with sim as controller:
        telemetry = Monitor(controller, history_size=2)
        app = create_app(telemetry)
        client = app.server.test_client()
        assets = ("bootstrap.min.css", "style.css", "watchdog.js", "panel.js")
        for path in ("/", "/_dash-layout", *(f"/assets/{name}" for name in assets)):
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
            "state": [
                {"id": "history-cursor", "property": "data", "value": 0},
                {"id": "connection-generation", "property": "data", "value": 0},
            ],
        }

        def refresh(expected: str) -> dict:
            before = len(requests)
            response = client.post("/_dash-update-component", json=payload)
            assert response.status_code == 200, response.data
            data = response.get_json()["response"]

            def collect(node: object) -> None:
                if isinstance(node, list):
                    for child in node:
                        collect(child)
                elif isinstance(node, dict):
                    props = node.get("props", {})
                    if "id" in props:
                        data[props["id"]] = props
                    collect(props.get("children"))

            collect(data["sample"]["children"])
            assert data["health"]["children"] == expected, data
            assert len(requests) == before, "GUI callback must read only the cache"
            return data

        refresh("NO DATA")
        telemetry.poll_once()
        refresh("LIVE")
        assert b"SIMULATOR" in client.get("/_dash-layout").data
        sim.set_faults(5, 999)
        telemetry.poll_once()
        fault_view = refresh("LIVE")
        assert fault_view["laser"]["children"] == "FAULT"
        assert "999" in fault_view["faults"]["children"]
        # Test-only malformed reply; never real hardware.
        sim._simulate_response = lambda request: b""
        telemetry.poll_once()
        error_view = refresh("ERROR")
        assert error_view["laser"]["children"] == "UNKNOWN"
        assert error_view["power-graph"]["extendData"][0]["y"][0][-1] is None
        telemetry.poll_once()
        refresh("ERROR")  # Failed sessions never recover implicitly.
        assert len(telemetry.snapshot()["history"]) == 2
    # The installed GUI queue must reach the installed driver and preserve readback.
    with SimulatedVerdi("V5", allow_writes=True, power_limit_w=0.5) as writable:
        controls_monitor = Monitor(writable)
        controls_app = create_app(controls_monitor)
        controls_monitor.poll_once()
        session = controls_monitor.controls
        token = session.new_client()
        session.submit(token, "apply-power", 1, "power", 0.25)
        controls_monitor.poll_once()
        action = session.snapshot()["actions"][-1]
        assert action["state"] == "verified" and action["readback"]["actual"] == 0.25
        assert controls_app.server.test_client().get("/_dash-layout").status_code == 200
        controls_monitor.close()
    runtime = GuiSession(model="V2")
    lifecycle_app = create_app(runtime.monitor, session=runtime)
    layout = lifecycle_app.server.test_client().get("/_dash-layout").data
    assert all(
        name.encode() in layout
        for name in ("connection-toggle", "close-application", "monitoring-interval")
    )
    runtime.submit("connect")
    runtime.step()
    assert (
        runtime.snapshot()["connected"]
        and runtime.monitor.controls.controller.last_transaction is None
    )
    control = runtime.monitor.controls
    control.submit(control.new_client(), "resume-polling", 1, "polling", True)
    runtime.step()
    assert runtime.monitor.latest()["health"] == "LIVE"
    runtime.submit("close")
    runtime.step()
    assert runtime.stop.is_set() and not runtime.snapshot()["connected"]
    print(
        "PASS: installed GUI assets, NO DATA/LIVE/FAULT/ERROR callbacks, "
        "bounded cache, queued power control, explicit connection and monitoring lifecycle; "
        f"Dash {version('dash')}, Plotly {version('plotly')}, pySerial {version('pyserial')}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui-smoke", action="store_true", help=argparse.SUPPRESS)
    if parser.parse_args().gui_smoke:
        gui_smoke()
    else:
        main()
