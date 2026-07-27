"""
mcp_client.py — Local MCP tool router.

Calls your local MCP servers via HTTP instead of executing tools inline.
This is the bridge between claude.py and the MCP servers running on localhost.

When deploying:
  1. Update MCP_SERVER_URLS to point at your public URLs
  2. Switch claude.py to use anthropic_client.beta.messages.create(mcp_servers=...)
  3. Delete this file — Anthropic handles routing directly
"""
import json
import httpx
import asyncio
import re
from datetime import date, datetime, timedelta
from config import settings

# ── MCP server URLs ────────────────────────────────────────────────────────

EHR_PORTS = {
    "hapi_fhir": 5003,
    "epic":      5004,
    "athena":    5005,
    "cerner":    5006,
}

EHR_BACKEND = settings.ehr_backend

EHR_HTTP_PORTS = {
    "hapi_fhir": 5103,
    "epic":      5104,
    "athena":    5105,
    "cerner":    5106,
}

MCP_SERVER_URLS = {
    "lookup_patient":      "http://localhost:5101",
    "check_eligibility":   "http://localhost:5102",
    "fhir_get_slots":      f"http://localhost:{EHR_HTTP_PORTS[EHR_BACKEND]}",
    "fhir_create_patient": f"http://localhost:{EHR_HTTP_PORTS[EHR_BACKEND]}",
}


# ── Slot generator — mirrors hapi_fhir/server.py's logic exactly, so the
#    fallback behaves identically to the real Docker-backed tool ───────────

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
    """Generate 2 slots PER DEPARTMENT on EVERY weekday — matches
    hapi_fhir/server.py's real logic exactly, so the fallback never
    behaves differently (e.g. having gaps the real tool doesn't)."""
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
    """Parse a time preference string into a minimum hour (24h)."""
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

    if month:
        target_month = _month_number(month)
        if target_month:
            matched = [s for s in matched if s["date_obj"].month == target_month]

    if target_date:
        try:
            parsed = datetime.strptime(target_date.strip(), "%m/%d/%Y").date()
            matched = [s for s in matched if s["date_obj"] == parsed]
        except ValueError:
            pass

    if week:
        w = week.lower().strip()
        if w in ("this", "next"):
            start, end = _week_bounds(w)
            matched = [s for s in matched if start <= s["date_obj"] <= end]

    if day:
        day_lower = day.lower().strip()
        matched = [s for s in matched if day_lower in s["day"]]

    if after_time:
        cutoff = _parse_hour_cutoff(after_time)
        matched = [s for s in matched if _slot_hour(s["time"]) >= cutoff]
    if before_time:
        cutoff = _parse_hour_cutoff(before_time)
        matched = [s for s in matched if _slot_hour(s["time"]) < cutoff]

    return [{k: v for k, v in s.items() if k != "date_obj"} for s in matched]


# ── MCP HTTP client ────────────────────────────────────────────────────────

async def call_tool(tool_name: str, tool_input: dict) -> str:
    """
    Call a local MCP server tool via HTTP POST.
    Falls back to inline execution if the MCP server is unreachable.
    """
    base_url = MCP_SERVER_URLS.get(tool_name)
    if not base_url:
        return json.dumps({"error": f"No MCP server registered for tool: {tool_name}"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/call",
                json={"tool": tool_name, "input": tool_input},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("result", json.dumps(data))

    except httpx.ConnectError:
        print(f"[mcp_client] {tool_name}: MCP server unreachable at {base_url} — using fallback")
        return await _fallback(tool_name, tool_input)

    except httpx.TimeoutException:
        print(f"[mcp_client] {tool_name}: MCP server timed out — using fallback")
        return await _fallback(tool_name, tool_input)

    except Exception as e:
        print(f"[mcp_client] {tool_name}: unexpected error — {e}")
        return json.dumps({"error": str(e)})


# ── Inline fallback ────────────────────────────────────────────────────────

async def _fallback(tool_name: str, tool_input: dict) -> str:
    """Inline fallback if MCP server is down."""
    from services.patient_lookup import search_patient as find_patient
    from services.fhir_client import create_patient

    def check_eligibility_mock(insurance_id: str, payer: str) -> dict:
        if not insurance_id or insurance_id == "NONE":
            return {"covered": False, "status": "not_found", "payer": payer}
        if "medicare" in payer.lower():
            return {"covered": True, "status": "active", "plan": "Medicare Part B", "copay": 20.00, "payer": payer}
        if insurance_id.upper().startswith("TERM"):
            return {"covered": False, "status": "inactive", "payer": payer}
        return {"covered": True, "status": "active", "plan": "PPO", "copay": 25.00,
                "deductible": 1500.00, "payer": payer, "member_id": insurance_id}

    try:
        # ── lookup_patient ─────────────────────────────────────────────────
        if tool_name == "lookup_patient":
            record = find_patient(
                name=tool_input.get("name"),
                dob=tool_input.get("dob") or None,
            )
            return json.dumps(record) if record else "NOT_FOUND"

        # ── check_eligibility ──────────────────────────────────────────────
        if tool_name == "check_eligibility":
            result = check_eligibility_mock(
                insurance_id=tool_input.get("insurance_id", ""),
                payer=tool_input.get("payer", ""),
            )
            return json.dumps(result)

        # ── fhir_get_slots ─────────────────────────────────────────────────
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
                return json.dumps({
                    "slots": [],
                    "message": "No slots match that filter.",
                })
            return json.dumps({"slots": matched, "message": "available"})

        # ── fhir_create_patient ────────────────────────────────────────────
        if tool_name == "fhir_create_patient":
            fhir_id = create_patient(tool_input)
            return json.dumps({"fhir_id": fhir_id or "pending", "status": "created"})

    except Exception as e:
        print(f"[mcp_client] fallback failed for {tool_name}: {e}")
        return json.dumps({"error": str(e)})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


# ── Sync wrapper ───────────────────────────────────────────────────────────

def call_tool_sync(tool_name: str, tool_input: dict) -> str:
    """Sync wrapper for use in non-async contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, call_tool(tool_name, tool_input))
                return future.result()
        return loop.run_until_complete(call_tool(tool_name, tool_input))
    except Exception as e:
        return json.dumps({"error": str(e)})