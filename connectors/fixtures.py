"""Fixed test data and failure-mode triggers for the three mocks.

Backlog ENG-04 産出: '固定測試資料及故障模式'. Keeping these as named
constants (rather than ad hoc literals inside each test) is what lets a
reviewer re-trigger the same SD-C-* negative scenario without reading the
mock's internals.
"""
from __future__ import annotations

from datetime import date

TENANT_ID = "00000000-0000-4000-8000-000000000001"
OTHER_TENANT_ID = "00000000-0000-4000-8000-000000000002"

# --- ExperienceReservationMock fixtures -------------------------------------------------
# One seat free, one sold out: exercises both the SUCCEEDED and the
# SESSION_CAPACITY_EXCEEDED FAILED/NOT_APPLIED failure mode.
EXPERIENCE_SESSIONS = {
    "sess-city-tour-0900": 4,
    "sess-sold-out-1400": 0,
}

# --- PmsNightlyMock fixtures -------------------------------------------------------------
# Room 101 has capacity for every night in the fixed Dec 2026 window except
# 2026-12-24, which is fully booked: exercises both the SUCCEEDED
# cross-night query and the ROOM_NIGHT_SOLD_OUT failure mode.
PMS_ROOM_NIGHT_CAPACITY = {
    ("room-101", date(2026, 12, 20)): 1,
    ("room-101", date(2026, 12, 21)): 1,
    ("room-101", date(2026, 12, 22)): 1,
    ("room-101", date(2026, 12, 23)): 1,
    ("room-101", date(2026, 12, 24)): 0,
}
PMS_AVAILABLE_CHECK_IN = date(2026, 12, 20)
PMS_AVAILABLE_CHECK_OUT = date(2026, 12, 22)
PMS_SOLD_OUT_CHECK_IN = date(2026, 12, 23)
PMS_SOLD_OUT_CHECK_OUT = date(2026, 12, 25)

# --- OtaDelayedPublicationMock fixtures ---------------------------------------------------
OTA_CHANNEL_ACCEPTING = "ota-channel-a"
OTA_SERVICE_VERSION = "3"

FIXED_NOW = "2026-11-26T00:00:00Z"
