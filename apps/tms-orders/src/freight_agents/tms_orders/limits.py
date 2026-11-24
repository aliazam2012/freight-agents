"""Weight limits, each with its source. Read 2026-11-23.

Payloads: C.H. Robinson, "Contract Trailer Equipment Guide" (2017), appendix A (dry van)
and appendix B (reefer), maximum freight weight per trailer:
https://www.chrobinson.com/en-US/-/media/ChRobinson/documents/Truckload%20Equipment%20Guide.pdf

Gross: 23 U.S.C. 127(a), 80,000 pounds overall gross weight on the Interstate System,
https://www.law.cornell.edu/uscode/text/23/127
"""

from freight_agents.tms_orders.domain import Equipment

PAYLOAD_LB = {
    Equipment.DRY_VAN_53: 44_000,  # 53' high cube dry van
    Equipment.DRY_VAN_48: 45_000,  # 48' high cube dry van
    Equipment.REEFER_53: 43_500,  # 53' reefer
}
GROSS_LB = 80_000
