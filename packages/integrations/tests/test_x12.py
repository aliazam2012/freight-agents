import pytest
from freight_agents.integrations.x12 import (
    Separators,
    X12Error,
    parse_interchange,
    write_interchange,
)

BODY = [
    ["B2", "", "EXFL", "", "LHG-104201", "L", "PP"],
    ["B2A", "00", "LT"],
    ["N7", "", "0", "", "", "", "", "", "", "", "", "TL", "", "", "", "5300"],
]


def _default() -> str:
    return write_interchange(
        sender="LHG",
        receiver="EXFL",
        control="000000014",
        group_control="2695",
        when="202612091500",
        functional_id="SM",
        sets=[("204", "0001", BODY)],
    )


def test_a_written_interchange_parses_back() -> None:
    ix = parse_interchange(_default())
    assert ix.control == "000000014"
    assert ix.sender == "LHG"
    assert ix.receiver == "EXFL"
    (group,) = ix.groups
    assert group.control == "2695"
    assert group.version == "004010"
    (ts,) = group.sets
    assert ts.set_id == "204"
    assert ts.body == BODY


def test_separators_come_from_the_isa_and_line_breaks_are_ignored() -> None:
    other = Separators(element="|", component=":", segment="!", repetition="^")
    text = write_interchange(
        sender="LHG",
        receiver="EXFL",
        control="000000014",
        group_control="2695",
        when="202612091500",
        functional_id="SM",
        sets=[("204", "0001", BODY)],
        separators=other,
    )
    assert "|" in text
    broken_lines = _default().replace("~", "~\r\n")
    for variant in (text, broken_lines, "﻿" + _default()):
        assert parse_interchange(variant).groups[0].sets[0].body == BODY


@pytest.mark.parametrize(
    ("change", "names"),
    [
        (lambda t: t.replace("IEA*1*000000014", "IEA*1*000000099"), "IEA"),
        (lambda t: t.replace("GE*1*2695", "GE*1*2696"), "GE"),
        (lambda t: t.replace("GE*1*", "GE*2*"), "GE"),
        (lambda t: t.replace("SE*5*0001", "SE*9*0001"), "SE"),
        (lambda t: t.replace("SE*5*0001", "SE*5*0002"), "SE"),
        (lambda t: t[: t.index("IEA")], "IEA"),
        (lambda t: t.replace("ISA*", "ISX*", 1), "ISA"),
        (lambda t: t[:50], "ISA"),
    ],
)
def test_a_broken_envelope_names_the_segment(change, names) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(X12Error) as err:
        parse_interchange(change(_default()))
    assert err.value.segment == names
