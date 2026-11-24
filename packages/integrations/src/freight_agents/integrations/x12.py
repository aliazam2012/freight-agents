"""ASC X12 interchanges: read and write the envelope, leave each transaction set to its app.

The ISA segment is fixed width, so it names the separators: the element separator
is its fourth character, ISA16 (the component separator) its 105th, and the segment
terminator the character after it. Line breaks after terminators are common and
ignored. Every envelope count and control number is checked, and a mismatch raises
`X12Error` naming the segment, so a broken file is refused rather than half read.

Envelope rules as given in the CN 204 implementation guide, version 4010 (cn.ca, read
2026-11-23): ISA13 equals IEA02, IEA01 counts the groups, GS06 equals GE02, GE01
counts the transaction sets, ST02 equals SE02, SE01 counts the segments from ST to SE.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

ISA_LENGTH = 106  # the ISA segment, terminator included
VERSION = "00401"
GROUP_VERSION = "004010"

Segment = list[str]


class X12Error(ValueError):
    def __init__(self, segment: str, message: str) -> None:
        super().__init__(f"{segment}: {message}")
        self.segment = segment


@dataclass(frozen=True)
class Separators:
    element: str = "*"
    component: str = ">"
    segment: str = "~"
    repetition: str | None = None  # from version 4020 on; 4010 sends "U" in ISA11


DEFAULT = Separators()


@dataclass(frozen=True)
class TransactionSet:
    set_id: str
    control: str
    body: list[Segment]  # the segments between ST and SE


@dataclass(frozen=True)
class Group:
    functional_id: str
    sender: str
    receiver: str
    date: str  # CCYYMMDD
    time: str  # HHMM
    control: str
    version: str
    sets: list[TransactionSet] = field(default_factory=list)


@dataclass(frozen=True)
class Interchange:
    sender: str
    receiver: str
    control: str
    separators: Separators
    groups: list[Group] = field(default_factory=list)


def _segments(text: str, sep: Separators) -> list[Segment]:
    out = []
    for raw in text.split(sep.segment):
        raw = raw.strip("\r\n\t ")
        if raw:
            out.append(raw.split(sep.element))
    return out


def parse_interchange(text: str) -> Interchange:
    text = text.lstrip("﻿\r\n\t ")
    if len(text) < ISA_LENGTH or not text.startswith("ISA"):
        raise X12Error("ISA", "the interchange does not start with a complete ISA segment")
    sep = Separators(element=text[3], component=text[104], segment=text[105])
    isa = text[: ISA_LENGTH - 1].split(sep.element)
    if len(isa) != 17:
        raise X12Error("ISA", f"expected 16 elements, found {len(isa) - 1}")
    control = isa[13]
    segments = _segments(text[ISA_LENGTH:], sep)
    groups: list[Group] = []
    i = 0
    while i < len(segments) and segments[i][0] == "GS":
        gs = segments[i]
        sets: list[TransactionSet] = []
        i += 1
        while i < len(segments) and segments[i][0] == "ST":
            st = segments[i]
            start = i
            i += 1
            while i < len(segments) and segments[i][0] not in ("SE", "ST", "GE", "IEA"):
                i += 1
            if i == len(segments) or segments[i][0] != "SE":
                raise X12Error("SE", f"transaction set {st[2]} has no SE trailer")
            se = segments[i]
            count = i - start + 1
            if se[1] != str(count):
                raise X12Error("SE", f"SE01 says {se[1]} segments, the set has {count}")
            if se[2] != st[2]:
                raise X12Error("SE", f"SE02 {se[2]} does not match ST02 {st[2]}")
            sets.append(TransactionSet(st[1], st[2], segments[start + 1 : i]))
            i += 1
        if i == len(segments) or segments[i][0] != "GE":
            raise X12Error("GE", f"group {gs[6]} has no GE trailer")
        ge = segments[i]
        if ge[1] != str(len(sets)):
            raise X12Error("GE", f"GE01 says {ge[1]} transaction sets, the group has {len(sets)}")
        if ge[2] != gs[6]:
            raise X12Error("GE", f"GE02 {ge[2]} does not match GS06 {gs[6]}")
        groups.append(Group(gs[1], gs[2], gs[3], gs[4], gs[5], gs[6], gs[8], sets))
        i += 1
    if i == len(segments) or segments[i][0] != "IEA":
        raise X12Error("IEA", "the interchange has no IEA trailer")
    iea = segments[i]
    if iea[1] != str(len(groups)):
        raise X12Error("IEA", f"IEA01 says {iea[1]} groups, the interchange has {len(groups)}")
    if iea[2] != control:
        raise X12Error("IEA", f"IEA02 {iea[2]} does not match ISA13 {control}")
    return Interchange(isa[6].strip(), isa[8].strip(), control, sep, groups)


def write_interchange(
    *,
    sender: str,
    receiver: str,
    control: str,
    group_control: str,
    when: str,  # CCYYMMDDHHMM
    functional_id: str,
    sets: Sequence[tuple[str, str, Sequence[Segment]]],
    separators: Separators = DEFAULT,
) -> str:
    """One interchange with one functional group; `sets` holds (set id, control, body)."""
    e, t = separators.element, separators.segment
    isa = e.join(
        [
            "ISA", "00", " " * 10, "00", " " * 10,
            "ZZ", f"{sender:<15}", "ZZ", f"{receiver:<15}",
            when[2:8], when[8:12], "U", VERSION, f"{int(control):09d}", "0", "P",
            separators.component,
        ]
    )  # fmt: skip
    lines = [isa]
    lines.append(
        e.join(["GS", functional_id, sender, receiver, when[:8], when[8:12], group_control,
                "X", GROUP_VERSION])
    )  # fmt: skip
    for set_id, set_control, body in sets:
        lines.append(e.join(["ST", set_id, set_control]))
        lines.extend(e.join(segment) for segment in body)
        lines.append(e.join(["SE", str(len(body) + 2), set_control]))
    lines.append(e.join(["GE", str(len(sets)), group_control]))
    lines.append(e.join(["IEA", "1", f"{int(control):09d}"]))
    return t.join(lines) + t
