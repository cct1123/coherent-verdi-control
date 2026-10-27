"""Execute the hardware sweep notebook using real controller code and fake serial I/O."""

import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fakes import RecordingVerdi

from coherent_verdi import VerdiError

NOTEBOOK = Path(__file__).resolve().parents[1] / "examples/07_power_current_sweep.ipynb"


@pytest.fixture
def sweep(peer, monkeypatch):
    # Use a normal workspace directory: pytest's private Windows temp ACL is
    # inaccessible under some sandbox configurations. Keep these ignored records.
    output_dir = NOTEBOOK.parents[1] / "tmp" / f"sweep-test-{uuid4().hex}"
    output_dir.mkdir(parents=True)
    monkeypatch.chdir(output_dir)
    sim = RecordingVerdi("V2", allow_writes=True, prompt=True)
    sim.set_key(True)
    sim._apply("L=1")  # This lesson starts with the laser already ON.
    clock = [0.0]
    write = peer.write
    read = peer.read

    def respond(request):
        assert not peer.pending, "Previous frame was not consumed"
        clock[0] += 0.001  # Deterministic serial transaction duration for notebook timestamps.
        peer.responses.append(sim._simulate_response(request))
        return write(request)

    def timed_read(size):
        if not peer.pending:
            clock[0] += 3  # Let pySerial's timeout expire on incomplete fake replies.
        return read(size)

    monkeypatch.setattr(peer, "write", respond)
    monkeypatch.setattr(peer, "read", timed_read)
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    monkeypatch.setattr("time.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr("builtins.input", lambda prompt: "STUDY" if "STUDY" in prompt else "SWEEP")
    namespace = {}
    settings = dict(
        PORT="FAKE-ONLY",
        MODEL="V2",
        SETPOINTS_W=[0.02, 0.04],
        POWER_LIMIT_W=0.1,
        SWEEP_DWELL_S=0.01,
        SETTLING_SAMPLE_COUNT=3,
        SETTLING_SAMPLE_PAUSE_S=0.005,
    )
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = {cell["id"]: cell for cell in notebook["cells"] if cell["cell_type"] == "code"}

    def run(stop_at=None, **overrides):
        for identifier, cell in cells.items():
            if identifier in ("sweep-time-plot-code", "sweep-results-plot-code"):
                continue  # Optional display-only code is compiled below, not executed in CI.
            source = compile("".join(cell["source"]), f"{NOTEBOOK.name}:{identifier}", "exec")
            exec(source, namespace)
            if "parameters" in cell["metadata"].get("tags", ()):
                namespace.update(settings | overrides)
            if identifier == stop_at:
                break
        return namespace

    def run_cell(identifier):
        exec(compile("".join(cells[identifier]["source"]), NOTEBOOK.name, "exec"), namespace)

    return sim, peer, namespace, run, run_cell


def test_notebook_schema_and_all_code_cells_compile():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert len({cell["id"] for cell in notebook["cells"]}) == len(notebook["cells"])
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            # Hardware runs retain their outputs, including failed-exchange evidence.
            assert cell["execution_count"] is None or type(cell["execution_count"]) is int
            assert isinstance(cell["outputs"], list)
            compile("".join(cell["source"]), cell["id"], "exec")


def test_study_and_sweep_save_samples_and_leave_laser_on_with_shutter_closed(sweep):
    sim, peer, namespace, run, _ = sweep
    run()
    commands = [request for request in peer.writes if not request.startswith(b"?")]
    expected = [
        b"P=0.0200\r\n",
        b"S=1\r\n",
        b"S=0\r\n",
        b"S=1\r\n",
        b"P=0.0200\r\n",
        b"P=0.0400\r\n",
        b"S=0\r\n",
    ]
    assert commands == expected
    assert peer.opens == peer.closes == 1 and not peer.pending
    assert sim._query("?L") == "1" and sim._query("?S") == "0"
    assert namespace["study_complete"] is True
    csv_path = namespace["csv_path"]
    assert list(Path.cwd().glob("verdi_sweep_*.csv")) == [csv_path.resolve()]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["stage"] for row in rows] == ["study"] * 3 + ["sweep"] * 2
    samples = [row for row in rows if row["stage"] == "sweep"]
    assert len(samples) == 2
    assert [float(row["reported_power_w"]) for row in samples] == [0.02, 0.04]
    assert all(float(row["diode_current_a"]) == 12 for row in samples)
    assert set(samples[0]) == {
        "stage",
        "sampled_at_utc",
        "elapsed_s",
        "target_w",
        "reported_power_w",
        "diode_current_a",
        "diode_temp_c",
        "heatsink_temp_c",
        "sample_duration_s",
    }
    assert all(row["sampled_at_utc"] == row["sample_duration_s"] == "" for row in samples)
    assert float(samples[0]["diode_temp_c"]) == 25
    assert float(samples[0]["heatsink_temp_c"]) == 28
    assert 0 <= float(samples[0]["elapsed_s"]) < float(samples[1]["elapsed_s"])
    assert namespace["baseline"]["software_version"] == "SIMULATOR"
    assert not any(request.startswith(b"?D15V") for request in peer.writes)
    trace = [row for row in rows if row["stage"] == "study"]
    assert len(trace) == 3  # Time-series acquisition belongs only to the settling study.
    assert [float(row["target_w"]) for row in trace] == [0.02] * 3
    assert [float(row["reported_power_w"]) for row in trace] == [0.02] * 3
    assert all(float(row["diode_current_a"]) == 12 for row in trace)
    assert all(row["diode_temp_c"] == row["heatsink_temp_c"] == "" for row in trace)
    for row in trace:
        assert float(row["elapsed_s"]) >= 0
        assert float(row["sample_duration_s"]) > 0
    times = [float(row["elapsed_s"]) for row in trace]
    assert all(later - earlier >= 0.005 for earlier, later in zip(times, times[1:], strict=False))


@pytest.mark.parametrize("stages", [("study",), ("sweep",), ()])
def test_single_csv_can_save_one_stage_or_skip_empty_results(sweep, stages):
    _, _, namespace, run, run_cell = sweep
    run(stop_at="sweep-sweep-code")
    original_study = [dict(row) for row in namespace["time_samples"]]
    original_sweep = [dict(row) for row in namespace["samples"]]
    if "study" not in stages:
        namespace["time_samples"] = []
    if "sweep" not in stages:
        namespace["samples"] = []
    run_cell("sweep-save-code")
    paths = list(Path.cwd().glob("verdi_sweep_*.csv"))
    if stages:
        assert len(paths) == 1 and paths[0] == namespace["csv_path"].resolve()
        with paths[0].open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert {row["stage"] for row in rows} == set(stages)
        assert len(rows) == (3 if stages == ("study",) else 2)
    else:
        assert namespace["csv_path"] is None and not paths
    # Adding the discriminator must not mutate acquired rows in memory.
    if "study" in stages:
        assert namespace["time_samples"] == original_study
    if "sweep" in stages:
        assert namespace["samples"] == original_sweep
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize(
    "settings",
    [
        {"SETPOINTS_W": []},
        {"SETPOINTS_W": [0.002]},
        {"SETPOINTS_W": [0.11]},
        {"SETPOINTS_W": [float("nan")]},
        {"SETPOINTS_W": [float("inf")]},
        {"SETPOINTS_W": [True]},
        {"POWER_LIMIT_W": None},
        {"PORT": "<PORT>"},
        {"SETTLING_SAMPLE_PAUSE_S": None},
        {"SETTLING_SAMPLE_PAUSE_S": 0},
        {"SETTLING_SAMPLE_PAUSE_S": True},
        {"SETTLING_SAMPLE_PAUSE_S": float("nan")},
        {"SETTLING_SAMPLE_COUNT": None},
        {"SETTLING_SAMPLE_COUNT": True},
        {"SETTLING_SAMPLE_COUNT": 1},
    ],
)
def test_invalid_sweep_settings_stop_before_connection(sweep, settings):
    _, peer, _, run, _ = sweep
    with pytest.raises(ValueError):
        run(**settings)
    assert not peer.opens and not peer.writes


def test_single_setpoint_records_initial_transient_before_full_status_sample(sweep, monkeypatch):
    sim, _, namespace, run, _ = sweep
    query = sim._query
    readings = iter(("0.035", "0.025", "0.020"))

    def transient_query(request):
        if request == "?P" and query("?S") == "1":
            return next(readings, "0.020")
        return query(request)

    monkeypatch.setattr(sim, "_query", transient_query)
    run(SETPOINTS_W=[0.02])
    assert [row["reported_power_w"] for row in namespace["time_samples"]] == [0.035, 0.025, 0.02]
    assert 0 <= namespace["time_samples"][0]["elapsed_s"] < 0.005
    assert namespace["samples"][0]["reported_power_w"] == 0.02


@pytest.mark.parametrize("prefix", [b"level0 set!\r\n", b"level1 set!\r\nlevel0 set!\r\n"])
def test_level0_notice_during_second_study_sample_does_not_abort_or_replay(
    sweep, monkeypatch, prefix
):
    sim, peer, namespace, run, _ = sweep
    respond = sim._simulate_response
    power_reads = 0

    def notice(request):
        nonlocal power_reads
        wire = respond(request)
        if request == b"?P\r\n" and sim._query("?S") == "1":
            power_reads += 1
            if power_reads == 2:
                return prefix + wire
        return wire

    monkeypatch.setattr(sim, "_simulate_response", notice)
    run()
    assert power_reads == 5  # Three study samples, two sweep points; no replay.
    assert len(namespace["time_samples"]) == 3 and len(namespace["samples"]) == 2
    assert namespace["study_complete"]
    assert peer.writes.count(b"S=1\r\n") == peer.writes.count(b"S=0\r\n") == 2
    assert b"L=0\r\n" not in peer.writes and b"L=1\r\n" not in peer.writes


def test_cancel_sends_queries_only(sweep, monkeypatch):
    _, peer, namespace, run, run_cell = sweep
    monkeypatch.setattr("builtins.input", lambda prompt: "cancel")
    with pytest.raises(RuntimeError, match="Cancelled"):
        run()
    assert all(request.startswith(b"?") for request in peer.writes)
    assert "samples" not in namespace
    run_cell("sweep-disconnect-code")


def test_setup_keeps_shutter_closed_until_run(sweep):
    sim, peer, _, run, run_cell = sweep
    run(stop_at="sweep-setup-code")
    assert sim._query("?L") == "1"
    assert sim._query("?S") == "0"
    assert [q for q in peer.writes if not q.startswith(b"?")] == [b"P=0.0200\r\n"]
    run_cell("sweep-disconnect-code")


def test_study_closes_shutter_and_keeps_laser_on_for_review_before_sweep(sweep):
    sim, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-study-code")
    assert sim._query("?L") == "1" and sim._query("?S") == "0"
    assert len(namespace["time_samples"]) == 3 and namespace["samples"] == []
    assert b"L=0\r\n" not in peer.writes
    namespace["SWEEP_DWELL_S"] = 0.02  # Dwell can be adjusted after reviewing the study.
    run_cell("sweep-sweep-code")
    assert len(namespace["samples"]) == 2
    run_cell("sweep-disconnect-code")


def test_settling_time_can_be_chosen_after_the_study(sweep):
    _, _, namespace, run, run_cell = sweep
    run(stop_at="sweep-study-code", SWEEP_DWELL_S=None)
    assert namespace["study_complete"] and len(namespace["time_samples"]) == 3
    namespace["SWEEP_DWELL_S"] = 0.02
    run_cell("sweep-sweep-code")
    assert len(namespace["samples"]) == 2
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize("value", [None, 0, True, float("nan"), float("inf"), 3601])
def test_invalid_dwell_is_rejected_before_power_sweep_io(sweep, value):
    _, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-study-code")
    namespace["SWEEP_DWELL_S"] = value
    before = list(peer.writes)
    with pytest.raises(ValueError, match="SWEEP_DWELL_S"):
        run_cell("sweep-sweep-code")
    assert peer.writes == before
    run_cell("sweep-disconnect-code")


def test_power_sweep_cannot_skip_the_study(sweep):
    _, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-setup-code")
    before = list(peer.writes)
    with pytest.raises(RuntimeError, match="Complete the settling study"):
        run_cell("sweep-sweep-code")
    assert not namespace["study_complete"] and peer.writes == before
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize("cell", ["sweep-study-code", "sweep-sweep-code"])
@pytest.mark.parametrize("query", ["?M", "?D1SS", "?LBOSS", "?ESS", "?VSS"])
def test_mode_and_all_servos_are_checked_again_before_each_opening(sweep, monkeypatch, cell, query):
    sim, peer, _, run, run_cell = sweep
    run(stop_at="sweep-study-code" if cell == "sweep-sweep-code" else "sweep-setup-code")
    original = sim._query
    monkeypatch.setattr(
        sim, "_query", lambda q: ("0" if query == "?M" else "2") if q == query else original(q)
    )
    before = len(peer.writes)
    with pytest.raises(RuntimeError, match="Readiness changed"):
        run_cell(cell)
    assert all(q.startswith(b"?") for q in peer.writes[before:])
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize(
    "query,bad_value",
    [
        ("?K", "0"),
        ("?L", "0"),
        ("?S", "0"),
        ("?F", "999"),
        ("?SP", "0.04"),
        ("?M", "0"),
        ("?LBOSS", "2"),
    ],
)
def test_study_stops_on_changed_readiness_before_accepting_a_pair(
    sweep, monkeypatch, query, bad_value
):
    sim, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-setup-code")
    original = sim._query
    changed = False

    def change_during_pair(q):
        nonlocal changed
        if changed and q == query:
            return bad_value
        value = original(q)
        if q == "?P" and original("?S") == "1":
            changed = True
        return value

    monkeypatch.setattr(sim, "_query", change_during_pair)
    before = len(peer.writes)
    with pytest.raises(RuntimeError, match="Readiness changed"):
        run_cell("sweep-study-code")
    assert namespace["time_samples"] == [] and not namespace["study_complete"]
    assert peer.writes[before:].count(b"?P\r\n") == 1
    assert [q for q in peer.writes[before:] if not q.startswith(b"?")] == [b"S=1\r\n"]
    before_retry = list(peer.writes)
    with pytest.raises(RuntimeError, match="Complete the settling study"):
        run_cell("sweep-sweep-code")
    assert peer.writes == before_retry
    run_cell("sweep-disconnect-code")


def test_failed_new_study_invalidates_previous_completion(sweep, monkeypatch):
    sim, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-study-code")
    original = sim._query
    monkeypatch.setattr(sim, "_query", lambda q: "0" if q == "?M" else original(q))
    with pytest.raises(RuntimeError, match="Readiness changed"):
        run_cell("sweep-study-code")
    assert namespace["study_complete"] is False
    before = list(peer.writes)
    with pytest.raises(RuntimeError, match="Complete the settling study"):
        run_cell("sweep-sweep-code")
    assert peer.writes == before
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize("query,bad_value", [("?M", "0"), ("?LBOSS", "2")])
def test_sweep_rejects_a_point_if_readiness_changes_during_measurement(
    sweep, monkeypatch, query, bad_value
):
    sim, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-study-code")
    original = sim._query
    changed = False

    def change_during_point(q):
        nonlocal changed
        if changed and q == query:
            return bad_value
        value = original(q)
        if q == "?P" and original("?S") == "1":
            changed = True
        return value

    monkeypatch.setattr(sim, "_query", change_during_point)
    before = len(peer.writes)
    with pytest.raises(RuntimeError, match="Readiness changed"):
        run_cell("sweep-sweep-code")
    assert namespace["samples"] == []
    assert peer.writes[before:].count(b"?P\r\n") == 1
    assert [q for q in peer.writes[before:] if not q.startswith(b"?")] == [
        b"S=1\r\n",
        b"P=0.0200\r\n",
    ]
    run_cell("sweep-disconnect-code")


def test_sweep_waits_then_records_only_one_point_per_setting(sweep, monkeypatch):
    import time

    _, peer, _, run, _ = sweep
    waits = []
    sleep = time.sleep

    def wait(seconds):
        waits.append(seconds)
        sleep(seconds)

    monkeypatch.setattr(time, "sleep", wait)
    run()
    assert waits == [0.005, 0.005, 0.01, 0.01]  # Study pauses, then one dwell per setting.
    openings = [i for i, request in enumerate(peer.writes) if request == b"S=1\r\n"]
    close = peer.writes.index(b"S=0\r\n", openings[1])
    sweep_reads = peer.writes[openings[1] + 1 : close]
    assert sweep_reads.count(b"?P\r\n") == sweep_reads.count(b"?D1C\r\n") == 2


@pytest.mark.parametrize("cell", ["sweep-study-code", "sweep-sweep-code"])
def test_run_rechecks_state_after_setup_before_opening(sweep, cell):
    sim, peer, _, run, run_cell = sweep
    run(stop_at="sweep-study-code" if cell == "sweep-sweep-code" else "sweep-setup-code")
    sim.set_key(False)
    before = len(peer.writes)
    with pytest.raises(RuntimeError, match="Readiness changed"):
        run_cell(cell)
    assert all(q.startswith(b"?") for q in peer.writes[before:])
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize(
    "condition", ["key_off", "standby", "shutter_open", "fault", "servo_unlocked"]
)
def test_unready_state_stops_before_writes(sweep, condition, monkeypatch):
    sim, peer, _, run, run_cell = sweep
    if condition == "key_off":
        sim.set_key(False)
    elif condition == "standby":
        sim._apply("L=0")
    elif condition == "shutter_open":
        sim._apply("L=1")
        sim._apply("S=1")
    elif condition == "fault":
        sim.set_faults(999)
    else:
        query = sim._query
        monkeypatch.setattr(
            sim, "_query", lambda request: "2" if request == "?LBOSS" else query(request)
        )
    with pytest.raises(RuntimeError):
        run()
    assert all(request.startswith(b"?") for request in peer.writes)
    run_cell("sweep-disconnect-code")


@pytest.mark.parametrize("cell", ["sweep-study-code", "sweep-sweep-code"])
def test_timeout_after_open_keeps_last_exchange_without_automatic_cleanup(sweep, monkeypatch, cell):
    sim, peer, namespace, run, run_cell = sweep
    run(stop_at="sweep-study-code" if cell == "sweep-sweep-code" else "sweep-setup-code")
    # Drop reply termination/prompt only at the first open-shutter power sample.
    write = peer.write

    def incomplete_power(request):
        if request == b"?P\r\n" and sim._query("?S") == "1":
            peer.writes.append(request)
            peer.pending.extend(b"partial")
            return len(request)
        return write(request)

    monkeypatch.setattr(peer, "write", incomplete_power)
    with pytest.raises(VerdiError, match="timed out"):
        run_cell(cell)
    assert namespace["laser"].failed
    assert not namespace["samples"] and "csv_path" not in namespace
    commands = [request for request in peer.writes if not request.startswith(b"?")]
    expected = [b"P=0.0200\r\n"]
    if cell == "sweep-sweep-code":
        expected += [b"S=1\r\n", b"S=0\r\n", b"S=1\r\n", b"P=0.0200\r\n"]
    else:
        expected += [b"S=1\r\n"]
    assert commands == expected
    assert namespace["laser"].last_transaction["response"] == b"partial"
    before = list(peer.writes)
    assert namespace["laser"].last_transaction["response"] == b"partial"
    assert peer.writes == before
    run_cell("sweep-disconnect-code")
