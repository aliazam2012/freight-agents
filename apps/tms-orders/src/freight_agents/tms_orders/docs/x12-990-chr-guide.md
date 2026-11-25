---
title: X12 990 Response to a Load Tender, version 4010 (C.H. Robinson truckload specification)
source_url: https://www.chrobinson.com/en-US/-/media/ChRobinson/documents/carrier-specs-docs/truckload-carrier-specs/CHR990IB.pdf?la=en-US
publisher: C.H. Robinson Worldwide, truckload carrier EDI specification version 1.2
read_on: 2026-11-23
---

Plain-language summary of one trading partner's published specification.

## Envelope

The functional group of a 990 uses GS01 code GF, response to a load tender.

## B1 Beginning segment

B101 is the carrier's SCAC and B102 the shipment identification number from the tender. B103 is a date as CCYYMMDD. B104, the reservation action code, says what the carrier did: A reservation accepted, D reservation cancelled, R delete, which this partner treats as a decline, and U change, which it treats as an acceptance. Partners differ on D and R, so each partner's guide decides.
