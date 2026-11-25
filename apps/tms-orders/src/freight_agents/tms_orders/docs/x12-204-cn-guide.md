---
title: X12 204 Motor Carrier Load Tender, version 4010 (CN implementation guide)
source_url: https://www.cn.ca/-/media/files/customer-centre/customer-centre-documents/204-implementation-guide-4010.pdf
publisher: Canadian National Railway Company, EDI implementation guide for trading partners
read_on: 2026-11-23
---

Plain-language summary of one trading partner's published guide. Partners restrict and extend the X12 standard, so each partner's guide governs its own tenders.

## Envelope

An interchange starts with an ISA segment of fixed width and ends with IEA. ISA13 is the interchange control number and IEA02 repeats it. ISA16 is the component element separator. A functional group starts with GS (GS06 is the group control number) and ends with GE, whose GE02 repeats it and GE01 counts the transaction sets. Each transaction set starts with ST (ST01 204, ST02 the control number) and ends with SE, whose SE01 counts every segment from ST to SE and SE02 repeats ST02.

## B2 Beginning segment

B202 carries the carrier's Standard Carrier Alpha Code (SCAC). B204 is the shipment identification number. B205 is the weight unit (L for pounds). B206 is the method of payment, such as PP for prepaid.

## B2A Set purpose

B2A01 says what the tender is: 00 original, 01 cancellation, 04 update. B2A02 LT marks a load tender for a truckload carrier.

## G62 Dates and times

Dates are CCYYMMDD and times HHMM. Qualifiers in this guide: 64 must respond by, 10 requested pickup date, 38 ship no later than, 68 requested delivery date, 54 deliver no later than. G6205 LT marks local time.

## S5 Stops and N1 parties

Each stop is an S5 loop: S501 the stop sequence number, S502 the reason, CL complete load at pickup and CU complete unload at delivery. N1 entity codes include OB ordered by, SH shipper, BT bill to, SF ship from and ST ship to, with N3 street and N4 city, state and postal code.

## N7, AT8 and L3 Equipment and weights

N7 describes the equipment: N711 the equipment description code and N715 the length, where 5300 means 53 feet. AT8 carries the weight qualifier (G gross), the unit (L pounds), the weight and the piece count. L3 gives the total weight, its qualifier and unit, and the lading quantity.
