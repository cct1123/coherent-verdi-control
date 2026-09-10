"""TEST-002: independent golden cases transcribed from manual Table 5-1."""

import pytest

from coherent_verdi import DeviceError, ProtocolError, Query
from coherent_verdi.protocol import (
    QUERY_SPECS,
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


def test_catalog_complete_with_manual_references():
    assert len(QUERY_SPECS) == len(Query) == 42
    assert all(spec.page in {"5-6", "5-7", "5-8", "5-9", "5-10"} for spec in QUERY_SPECS.values())
