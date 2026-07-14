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
from datetime import date, timedelta
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


# ── Slot generator ─────────────────────────────────────────────────────────

def _get_slots() -> list[dict]:
    """Generate slots dynamically for the next 10 weekdays."""
    today    = date.today()
    weekdays = []
    d        = today + timedelta(days=1)
    while len(weekdays) < 10:
        if d.weekday() < 5:
            weekdays.append(d)
        d += timedelta(days=1)

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    months    = ["Jan","Feb","Mar","Apr","May","Jun",
                 "Jul","Aug","Sep","Oct","Nov","Dec"]

    def fmt(d: date) -> str:
        return f"{day_names[d.weekday()]} {months[d.month-1]} {d.day}"

    def dow(d: date) -> str:
        return d.strftime("%A").lower()

    return [
        {"id": "s1",  "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": fmt(weekdays[0]), "time": "9:00 AM",  "day": dow(weekdays[0])},
        {"id": "s2",  "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": fmt(weekdays[0]), "time": "11:30 AM", "day": dow(weekdays[0])},
        {"id": "s3",  "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": fmt(weekdays[2]), "time": "1:00 PM",  "day": dow(weekdays[2])},
        {"id": "s4",  "doctor": "Dr. Chen",   "specialty": "Family Medicine", "date": fmt(weekdays[3]), "time": "8:30 AM",  "day": dow(weekdays[3])},
        {"id": "s5",  "doctor": "Dr. Chen",   "specialty": "Family Medicine", "date": fmt(weekdays[4]), "time": "10:00 AM", "day": dow(weekdays[4])},
        {"id": "s6",  "doctor": "Dr. Okafor", "specialty": "OB/GYN",         "date": fmt(weekdays[0]), "time": "2:00 PM",  "day": dow(weekdays[0])},
        {"id": "s7",  "doctor": "Dr. Okafor", "specialty": "OB/GYN",         "date": fmt(weekdays[3]), "time": "9:30 AM",  "day": dow(weekdays[3])},
        {"id": "s8",  "doctor": "Dr. Kim",    "specialty": "Cardiology",      "date": fmt(weekdays[1]), "time": "3:00 PM",  "day": dow(weekdays[1])},
        {"id": "s9",  "doctor": "Dr. Kim",    "specialty": "Cardiology",      "date": fmt(weekdays[4]), "time": "8:00 AM",  "day": dow(weekdays[4])},
        {"id": "s10", "doctor": "Dr. Rivera", "specialty": "Urgent Care",     "date": fmt(weekdays[0]), "time": "10:00 AM", "day": dow(weekdays[0])},
        {"id": "s11", "doctor": "Dr. Rivera", "specialty": "Urgent Care",     "date": fmt(weekdays[1]), "time": "3:30 PM",  "day": dow(weekdays[1])},
        {"id": "s12", "doctor": "Dr. Santos", "specialty": "Mental Health",   "date": fmt(weekdays[2]), "time": "11:00 AM", "day": dow(weekdays[2])},
        {"id": "s13", "doctor": "Dr. Santos", "specialty": "Mental Health",   "date": fmt(weekdays[5]), "time": "2:00 PM",  "day": dow(weekdays[5])},
        {"id": "s14", "doctor": "Dr. Adams",  "specialty": "Dermatology",     "date": fmt(weekdays[3]), "time": "9:00 AM",  "day": dow(weekdays[3])},
        {"id": "s15", "doctor": "Dr. Wong",   "specialty": "Pediatrics",      "date": fmt(weekdays[1]), "time": "2:30 PM",  "day": dow(weekdays[1])},
        {"id": "s16", "doctor": "Dr. Wong",   "specialty": "Pediatrics",      "date": fmt(weekdays[4]), "time": "8:00 AM",  "day": dow(weekdays[4])},
        {"id": "s17", "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": fmt(weekdays[6]), "time": "9:00 AM",  "day": dow(weekdays[6])},
        {"id": "s18", "doctor": "Dr. Chen",   "specialty": "Family Medicine", "date": fmt(weekdays[7]), "time": "11:00 AM", "day": dow(weekdays[7])},
        {"id": "s19", "doctor": "Dr. Kim",    "specialty": "Cardiology",      "date": fmt(weekdays[8]), "time": "10:00 AM", "day": dow(weekdays[8])},
        {"id": "s20", "doctor": "Dr. Santos", "specialty": "Mental Health",   "date": fmt(weekdays[9]), "time": "3:00 PM",  "day": dow(weekdays[9])},
    ]


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
    # Look for a number like "after 2pm" or "2:00 pm"
    import re
    match = re.search(r'(\d{1,2})', ft)
    if match:
        h = int(match.group(1))
        if "pm" in ft and h != 12:
            h += 12
        return h
    return 0


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
            dept        = tool_input.get("department", "").lower()
            filter_day  = tool_input.get("day", "").lower().strip()
            filter_time = tool_input.get("after_time", "").lower().strip()
            slots       = _get_slots()

            # Filter by department
            matched = [s for s in slots if dept in s["specialty"].lower()]
            if not matched:
                matched = slots[:3]

            # Filter by day if requested
            if filter_day:
                day_filtered = [s for s in matched if filter_day in s["day"]]
                if day_filtered:
                    matched = day_filtered
                else:
                    available_days = sorted(set(s["day"].capitalize() for s in matched))
                    return json.dumps({
                        "slots": [],
                        "message": f"No slots available on {filter_day.capitalize()} for {dept}.",
                        "available_days": available_days,
                    })

            # Filter by time if requested
            if filter_time:
                try:
                    cutoff        = _parse_hour_cutoff(filter_time)
                    time_filtered = [s for s in matched if _slot_hour(s["time"]) >= cutoff]
                    if time_filtered:
                        matched = time_filtered
                    else:
                        return json.dumps({
                            "slots": [],
                            "message": f"No slots after {filter_time} for {dept}.",
                            "available_times": [s["time"] for s in matched[:5]],
                        })
                except Exception:
                    pass

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