"""Simulator-only HTTP callback smoke test, also run against an isolated wheel install."""

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


def main() -> None:
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
    main()
