---
title: X12 204 Motor Carrier Load Tender, version 4010 (C.H. Robinson carrier specification)
source_url: https://www.chrobinson.com/en-CA/-/media/ChRobinson/documents/carrier-specs-docs/international-dray-carrier-specs/204%20International%20Dray%20Carrier%20Specs.pdf?la=en-CA
publisher: C.H. Robinson Worldwide, carrier EDI specification version 1.2 (modified 2020-12-07)
read_on: 2026-11-23
---

Plain-language summary of one trading partner's published specification.

## B2A Set purpose

B2A01 codes in this specification: 00 original, 01 cancellation, 04 change.

## G62 Appointment times at stops

Date qualifiers at stops: 10 requested pickup, 38 ship not later than, 54 deliver no later than, 68 requested delivery. Time qualifiers: 4 pickup requested scheduled time, 5 delivery requested scheduled time, K latest requested pickup time, L latest requested delivery time. Times are 24-hour HHMM.

## S5 Stop reasons

S502 reason codes used: LD load, UL unload, DT drop trailer, RT retrieval of trailer, DR deramp. S501 is the stop sequence.

## N7 Equipment

N711 equipment description codes used: TL trailer (not otherwise specified), CN container, CZ refrigerated container. N713 is a free-form temperature control field. N715 is the equipment length.

## L11 References

L1102 reference qualifiers include SI, the shipper's identifying number for the shipment, and PU, the pickup number.

## LH1 Hazardous material

LH101 and LH102 give the package type and count, LH103 the UN or NA identification number (six characters, such as UN1263), and LH110 the packing group in Roman numerals.
