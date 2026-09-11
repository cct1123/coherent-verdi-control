"""TEST-002: independent golden cases transcribed from manual Table 5-1."""

import pytest

from coherent_verdi import DeviceError, ProtocolError, Query, SimulatedTransport
from coherent_verdi.protocol import (
    decode_response,
    encode_instruction,
    parse_faults,
    parse_value,
)


@pytest.mark.parametrize("wire", [b"\r\n", b"Verdi>\r\n", b"L=0\r\n", b"Verdi> L=0\r\n"])
def test_command_acknowledgments(wire):
    assert decode_response("L=0", wire, query=False) == ""


@pytest.mark.parametrize(
    "wire",
    [
        b"1.234\r\n",
        b"Verdi> 1.234\r\n",
        b"?P1.234\r\n",
        b"Verdi> ?P 1.234\r\n",
    ],
)
def test_query_echo_prompt_layouts(wire):
    assert decode_response("?P", wire, query=True) == "1.234"


@pytest.mark.parametrize(
    "instruction,wire",
    [
        ("P=9", b"RANGE ERROR: P=9\r\n"),
        ("P=9", b"Verdi> P=9 RANGE ERROR: P=9\r\n"),
        ("BAD=0", b"Command Error: BAD=0\r\n"),
        ("?BAD", b"?BAD Query Error: ?BAD\r\n"),
    ],
)
def test_documented_errors(instruction, wire):
    with pytest.raises(DeviceError) as caught:
        decode_response(instruction, wire, query=instruction.startswith("?"))
    assert caught.value.instruction == instruction


@pytest.mark.parametrize(
    "wire", [b"", b"1\n", b"1\r", b"1\r\n2\r\n", b"\xff\r\n", b"\r\n", b"\x001\r\n", b"?P\r\n"]
)
def test_bad_query_framing(wire):
    with pytest.raises(ProtocolError):
        decode_response("?P", wire, query=True)


def test_no_generic_ok_ack():
    with pytest.raises(ProtocolError):
        decode_response("L=0", b"OK\r\n", query=False)


@pytest.mark.parametrize("wire", [b"\t1\r\n", b"1\x0b\r\n", b"\x0c1\r\n"])
def test_control_whitespace_is_not_trimmed_into_valid_data(wire):
    with pytest.raises(ProtocolError):
        decode_response("?L", wire, query=True)


def test_control_whitespace_is_not_an_acknowledgment():
    with pytest.raises(ProtocolError):
        decode_response("L=1", b"\t\r\n", query=False)


@pytest.mark.parametrize("instruction", ["?P\r\nL=1", "?P;L=1", "", "é", "?P\x00", "X" * 129])
def test_command_injection_rejected(instruction):
    with pytest.raises(ValueError):
        encode_instruction(instruction)


def test_golden_query_and_units():
    assert encode_instruction(Query.SET_POWER.value) == b"?SP\r\n"
    assert parse_value(Query.POWER, "1.234") == 1.234
    assert parse_value(Query.LBO_TEMP, "148.00") == 148.0
    assert parse_value(Query.LASER, "2") == 2
    assert parse_value(Query.SOFTWARE, "1.23") == "1.23"
    assert parse_value(Query.AVG_CURRENT_AND_DELTA, "12&0") == "12&0"


@pytest.mark.parametrize(
    "query,payload",
    [
        (Query.POWER, "nan"),
        (Query.POWER, "inf"),
        (Query.POWER, "1_000"),
        (Query.POWER, "1.5 W"),
        (Query.POWER, "-1"),
        (Query.POWER, "9" * 400),
        (Query.LASER, "3"),
        (Query.LASER, "1.0"),
        (Query.LASER, "True"),
        (Query.ETALON_SERVO, "4"),
        (Query.HEAD_HOURS, "-3"),
    ],
)
def test_invalid_values_not_coerced_to_good_states(query, payload):
    with pytest.raises(ProtocolError):
        parse_value(query, payload)


def test_fault_code_mapping_and_unknown_preservation():
    faults = parse_faults("3&5&6&21&999")
    assert [f.code for f in faults] == [3, 5, 6, 21, 999]
    assert faults[3].description == "Diode 1 over voltage fault"
    assert not faults[4].known
    assert parse_faults("SYSTEM OK") == ()


@pytest.mark.parametrize("payload", ["", "0", "1&", "1,2", "-1", "OK", "1&&2"])
def test_undocumented_fault_replies_are_not_assumed_clear(payload):
    with pytest.raises(ProtocolError):
        parse_faults(payload)


# TEST-016: independent transcription of all Table 5-4 rows, pp.5-6..5-10.
# Payloads are representative software vectors, not physical measurements.
MANUAL_QUERIES = [
    ("?ACAD", "AVG CURRENT AND DELTA", "5-6", None, "12&0", "12&0", ()),
    ("?BT", "BASEPLATE TEMP", "5-6", "degC", "30.00", 30.0, ()),
    (
        "?B",
        "BAUD RATE",
        "5-6",
        "baud",
        "19200",
        19200,
        (1200, 2400, 4800, 9600, 19200, 38400, 57600),
    ),
    ("?C", "CURRENT", "5-6", "A", "12.0", 12.0, ()),
    ("?D1C", "DIODE1 CURRENT", "5-6", "A", "12.0", 12.0, ()),
    ("?D1HST", "DIODE1 HEATSINK TEMP", "5-6", "degC", "28.00", 28.0, ()),
    ("?D1H", "DIODE1 HOURS", "5-6", "h", "42", 42.0, ()),
    ("?D1PC", "DIODE1 PHOTOCELL", "5-6", None, "0.0", "0.0", ()),
    ("?D1RCF", "DIODE1 RATED CURRENT FACTOR", "5-6", None, "1.0", "1.0", ()),
    ("?D1RCM", "DIODE1 RATED CURRENT MAX", "5-6", "A", "30.0", 30.0, ()),
    ("?D1SS", "DIODE1 SERVO STATUS", "5-7", None, "1", 1, (0, 1, 2, 3, 4, 5, 6)),
    ("?D1ST", "DIODE1 SET TEMP", "5-7", "degC", "25.00", 25.0, ()),
    ("?D1TD", "DIODE1 TEMP DRIVE", "5-7", None, "-100", "-100", ()),
    ("?D1T", "DIODE1 TEMP", "5-7", "degC", "25.00", 25.0, ()),
    ("?D15V", "DIODE1 5VREF SENSE", "5-7", None, "5.0", "5.0", ()),
    ("?DIOS", "DIODE OPTIMIZER STATUS", "5-7", None, "1", 1, (0, 1)),
    ("?ED", "ETALON DRIVE", "5-7", None, "-10", "-10", ()),
    ("?ESS", "ETALON SERVO STATUS", "5-7", None, "1", 1, (0, 1, 2, 3)),
    ("?EST", "ETALON SET TEMP", "5-7", "degC", "50.00", 50.0, ()),
    ("?ET", "ETALON TEMP", "5-7", "degC", "50.00", 50.0, ()),
    ("?F", "FAULTS", "5-8", None, "3&5&6", (3, 5, 6), ()),
    ("?FH", "FAULT HISTORY", "5-8", None, "SYSTEM OK", (), ()),
    ("?HH", "HEAD_HOURS", "5-8", "h", "100", 100.0, ()),
    ("?K", "KEYSWITCH", "5-8", None, "1", 1, (0, 1)),
    ("?L", "LASER", "5-8", None, "2", 2, (0, 1, 2)),
    ("?LBOD", "LBO DRIVE", "5-8", None, "-100", "-100", ()),
    ("?LBOH", "LBO HEATER", "5-8", None, "1", 1, (0, 1)),
    ("?LBOOS", "LBO OPTIMIZER STATUS", "5-8", None, "1", 1, (0, 1)),
    ("?LBOST", "LBO SET TEMP", "5-8", "degC", "148.00", 148.0, ()),
    ("?LBOSS", "LBO SERVO STATUS", "5-9", None, "1", 1, (0, 1, 2, 3, 4, 5, 6)),
    ("?LBOT", "LBO TEMP", "5-9", "degC", "148.00", 148.0, ()),
    ("?P", "LIGHT", "5-9", "W", "1.234", 1.234, ()),
    ("?LRS", "LIGHT REG STATUS", "5-9", None, "1", 1, (0, 1, 2, 3)),
    ("?M", "MODE", "5-9", None, "1", 1, (0, 1)),
    ("?PSH", "PS HOURS", "5-9", "h", "120", 120.0, ()),
    ("?SP", "SET LIGHT", "5-9", "W", "1.2345", 1.2345, ()),
    ("?S", "SHUTTER", "5-9", None, "0", 0, (0, 1)),
    ("?SV", "SOFTWARE", "5-9", None, "1.23", "1.23", ()),
    ("?VST", "VANADATE SET TEMP", "5-9", "degC", "30.00", 30.0, ()),
    ("?VT", "VANADATE TEMP", "5-9", "degC", "30.00", 30.0, ()),
    ("?VD", "VANADATE DRIVE", "5-10", None, "-100", "-100", ()),
    ("?VSS", "VANADATE SERVO STATUS", "5-10", None, "1", 1, (0, 1, 2, 3)),
]


@pytest.mark.parametrize("short,long,page,unit,payload,expected,choices", MANUAL_QUERIES)
def test_every_manual_query_value_and_codes(short, long, page, unit, payload, expected, choices):
    query = Query(short)
    value = parse_value(query, payload)
    if isinstance(expected, tuple):
        assert tuple(fault.code for fault in value) == expected
    else:
        assert value == expected and type(value) is type(expected)
    for code in choices:
        assert parse_value(query, str(code)) == code
    if choices:
        with pytest.raises(ProtocolError):
            parse_value(query, str(max(choices) + 1))


def test_manual_query_inventory_is_exact():
    assert {row[0] for row in MANUAL_QUERIES} == {query.value for query in Query}
    assert len(MANUAL_QUERIES) == len(Query)


@pytest.mark.parametrize(
    "echo,prompt", [(False, False), (False, True), (True, False), (True, True)]
)
@pytest.mark.parametrize(
    "instruction,error",
    [("P=9", "RANGE ERROR:"), ("BAD=0", "Command Error:"), ("?BAD", "Query Error:")],
)
def test_table_5_1_error_layouts_preserve_instruction_and_error(echo, prompt, instruction, error):
    prefix = ("Verdi> " if prompt else "") + (instruction + " " if echo else "")
    wire = (prefix + error + " " + instruction + "\r\n").encode()
    with pytest.raises(DeviceError) as caught:
        decode_response(instruction, wire, query=instruction.startswith("?"))
    assert caught.value.response == error + " " + instruction
    sim = SimulatedTransport(echo=echo, prompt=prompt)
    sim.connect()
    try:
        assert sim.exchange((instruction + "\r\n").encode()) == wire
    finally:
        sim.disconnect()


def test_complete_fault_catalog_including_manual_disagreement():
    # Table 5-4 plus Table 6-1. Code 47 is absent from Table 6-1 but retained.
    codes = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 16, 18, 19, 21, 25, 27, 28, 29, 30, 31, 40, 47)
    faults = parse_faults("&".join(map(str, codes)))
    assert tuple(fault.code for fault in faults) == codes
    assert all(fault.known for fault in faults)
    assert "interlock / emission lamp" in faults[0].description
    assert next(f for f in faults if f.code == 30).description == "Battery requires service"


def test_history_clear_does_not_establish_active_fault_clear_semantics():
    assert parse_value(Query.FAULT_HISTORY, "SYSTEM OK") == ()
    for payload in ("SYSTEM OK", "0", "OK", ""):
        with pytest.raises(ProtocolError):
            parse_value(Query.FAULTS, payload)
    assert parse_value(Query.FAULTS, "SYSTEM OK", active_fault_clear_reply="SYSTEM OK") == ()
