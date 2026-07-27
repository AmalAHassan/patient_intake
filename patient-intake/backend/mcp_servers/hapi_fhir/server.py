"""
MCP Server — HAPI FHIR (Default EHR)
Wraps fhir_client.py as MCP tools.
Runs on port 5003.
"""
import sys
import os
import json
import re
from datetime import date, datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn as _uvicorn
from dotenv import load_dotenv
import importlib

BACKEND_DIR = os.environ.get(
    "MCP_BACKEND_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)
sys.path.insert(0, BACKEND_DIR)


for env_path in [
    os.path.join(BACKEND_DIR, ".env"),
    os.path.join(BACKEND_DIR, "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

from fastmcp import FastMCP


fc = importlib.import_module("services.fhir_client")
create_patient = fc.create_patient
get_patient = fc.get_patient

mcp = FastMCP("hapi-fhir")


# ── Slot generation — tracks real date objects, not just display strings ──

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]
MONTHS    = ["Jan","Feb","Mar","Apr","May","Jun",
             "Jul","Aug","Sep","Oct","Nov","Dec"]

DEPARTMENT_DOCTORS = {
    "Family Medicine": ["Dr. Patel", "Dr. Chen"],
    "OB/GYN":          ["Dr. Okafor"],
    "Cardiology":      ["Dr. Kim"],
    "Urgent Care":     ["Dr. Rivera"],
    "Mental Health":   ["Dr. Santos"],
    "Dermatology":     ["Dr. Adams"],
    "Pediatrics":      ["Dr. Wong"],
}
TIME_SLOTS = ["9:00 AM", "11:30 AM", "1:00 PM", "3:00 PM"]


def _fmt_date(d: date) -> str:
    return f"{DAY_NAMES[d.weekday()]} {MONTHS[d.month-1]} {d.day}"


def _build_slots(days_ahead: int = 30) -> list[dict]:
    """
    Generate 2 slots PER DEPARTMENT on EVERY weekday across the next
    `days_ahead` weekdays (~6 calendar weeks). Every department gets
    consistent, realistic weekly availability — no more multi-week gaps
    for a given specialty, which the old shared-cycling-pattern approach
    created (a department only appearing once every ~7 weekdays).
    """
    today    = date.today()
    weekdays = []
    d        = today + timedelta(days=1)
    while len(weekdays) < days_ahead:
        if d.weekday() < 5:
            weekdays.append(d)
        d += timedelta(days=1)

    slots = []
    slot_num = 0
    for dept, doctors in DEPARTMENT_DOCTORS.items():
        for day_idx, day_obj in enumerate(weekdays):
            for slot_in_day in range(2):
                doctor   = doctors[(day_idx + slot_in_day) % len(doctors)]
                time_str = TIME_SLOTS[(day_idx * 2 + slot_in_day) % len(TIME_SLOTS)]
                slot_num += 1
                slots.append({
                    "id": f"s{slot_num}",
                    "doctor": doctor,
                    "specialty": dept,
                    "date_obj": day_obj,
                    "date": _fmt_date(day_obj),
                    "time": time_str,
                    "day": day_obj.strftime("%A").lower(),
                })
    return slots


MONTH_NAMES = ["january","february","march","april","may","june",
               "july","august","september","october","november","december"]


def _month_number(month: str) -> int | None:
    m = month.strip().lower()
    if m in MONTH_NAMES:
        return MONTH_NAMES.index(m) + 1
    return None


def _slot_hour(time_str: str) -> int:
    """Convert '9:00 AM' or '3:00 PM' to 24h integer."""
    h = int(time_str.split(":")[0])
    if "PM" in time_str and h != 12:
        h += 12
    if "AM" in time_str and h == 12:
        h = 0
    return h


def _parse_hour_cutoff(filter_time: str) -> int:
    """Parse a time preference string into an hour (24h)."""
    ft = filter_time.lower()
    if "afternoon" in ft:
        return 12
    if "evening" in ft:
        return 17
    if "morning" in ft:
        return 0
    match = re.search(r'(\d{1,2})', ft)
    if match:
        h = int(match.group(1))
        if "pm" in ft and h != 12:
            h += 12
        return h
    return 0


def _week_bounds(which: str) -> tuple[date, date]:
    """Return (start, end) dates for 'this' or 'next' calendar week (Mon-Sun)."""
    today = date.today()
    start_of_this_week = today - timedelta(days=today.weekday())
    if which == "next":
        start = start_of_this_week + timedelta(days=7)
    else:
        start = start_of_this_week
    end = start + timedelta(days=6)
    return start, end


def _filter_slots(
    department: str,
    day: str = "",
    after_time: str = "",
    before_time: str = "",
    week: str = "",
    target_date: str = "",
    month: str = "",
) -> list[dict]:
    slots = _build_slots()
    dept_lower = department.lower().strip()
    matched = [s for s in slots if dept_lower in s["specialty"].lower()]
    if not matched:
        matched = slots[:5]

    # Specific month, e.g. "august"
    if month:
        target_month = _month_number(month)
        if target_month:
            matched = [s for s in matched if s["date_obj"].month == target_month]

    # Specific date, e.g. "07/25/2026"
    if target_date:
        try:
            parsed = datetime.strptime(target_date.strip(), "%m/%d/%Y").date()
            matched = [s for s in matched if s["date_obj"] == parsed]
        except ValueError:
            pass

    # Week range: "this" or "next"
    if week:
        w = week.lower().strip()
        if w in ("this", "next"):
            start, end = _week_bounds(w)
            matched = [s for s in matched if start <= s["date_obj"] <= end]

    # Specific weekday name, e.g. "wednesday"
    if day:
        day_lower = day.lower().strip()
        matched = [s for s in matched if day_lower in s["day"]]

    # Time-of-day filters
    if after_time:
        cutoff = _parse_hour_cutoff(after_time)
        matched = [s for s in matched if _slot_hour(s["time"]) >= cutoff]
    if before_time:
        cutoff = _parse_hour_cutoff(before_time)
        matched = [s for s in matched if _slot_hour(s["time"]) < cutoff]

    # Strip internal date_obj before returning (not JSON-serializable)
    return [{k: v for k, v in s.items() if k != "date_obj"} for s in matched]


@mcp.tool
def fhir_create_patient(
    name: str,
    dob: str,
    phone: str = "",
    email: str = "",
    insurance_id: str = "",
    payer: str = "",
    department: str = "",
    reason: str = "",
    appointment_doctor: str = "",
    appointment_date: str = "",
    appointment_time: str = "",
) -> str:
    """
    Create a new patient record in HAPI FHIR.
    Called when intake is complete to persist the patient.
    Returns the FHIR patient ID.
    """
    data = {
        "name": name, "dob": dob, "phone": phone, "email": email,
        "insurance_id": insurance_id, "payer": payer, "department": department,
        "reason": reason, "appointment_doctor": appointment_doctor,
        "appointment_date": appointment_date, "appointment_time": appointment_time,
    }
    fhir_id = create_patient(data)
    return json.dumps({"fhir_id": fhir_id, "status": "created", "ehr": "hapi_fhir"})


@mcp.tool
def fhir_get_patient(patient_id: str) -> str:
    """Retrieve a patient record from HAPI FHIR by ID."""
    record = get_patient(patient_id)
    if not record:
        return json.dumps({"status": "not_found"})
    return json.dumps(record)


@mcp.tool
def fhir_get_slots(
    department: str,
    day: str = "",
    after_time: str = "",
    before_time: str = "",
    week: str = "",
    date: str = "",
    month: str = "",
) -> str:
    """
    Get available appointment slots for a department.
    Supports filtering by weekday name, time of day, week ("this"/"next"),
    a specific date (MM/DD/YYYY), or a month name (e.g. "august").
    """
    matched = _filter_slots(department, day, after_time, before_time, week, date, month)
    if not matched:
        return json.dumps({"slots": [], "message": "No slots match that filter."})
    return json.dumps({"slots": matched, "message": "available"})


http_app = FastAPI()

@http_app.post("/call")
async def call_tool_http(request: Request):
    body = await request.json()
    tool_name  = body.get("tool")
    tool_input = body.get("input", {})
    try:
        if tool_name == "fhir_get_slots":
            matched = _filter_slots(
                department=tool_input.get("department", ""),
                day=tool_input.get("day", ""),
                after_time=tool_input.get("after_time", ""),
                before_time=tool_input.get("before_time", ""),
                week=tool_input.get("week", ""),
                target_date=tool_input.get("date", ""),
                month=tool_input.get("month", ""),
            )
            if not matched:
                result = {"slots": [], "message": "No slots match that filter."}
            else:
                result = {"slots": matched, "message": "available"}
            return JSONResponse({"result": json.dumps(result)})

        if tool_name == "fhir_create_patient":
            fhir_id = create_patient(tool_input)
            return JSONResponse({"result": json.dumps({"fhir_id": fhir_id or "pending", "status": "created"})})

        return JSONResponse({"error": f"Tool not found: {tool_name}"}, status_code=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

if __name__ == "__main__":
    import threading, uvicorn as _uv

    def run_http():
        _uv.run(http_app, host="0.0.0.0", port=5103, log_level="error")

    threading.Thread(target=run_http, daemon=True).start()
    mcp.run(transport="sse", host="0.0.0.0", port=5003)