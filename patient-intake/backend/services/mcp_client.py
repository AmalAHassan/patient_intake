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
from config import settings

# ── MCP server URLs ────────────────────────────────────────────────────────
# Change these to public URLs when deploying

EHR_PORTS = {
    "hapi_fhir": 5003,
    "epic":      5004,
    "athena":    5005,
    "cerner":    5006,
}

EHR_BACKEND = settings.ehr_backend

# HTTP ports for /call endpoint (SSE ports + 100)
# SSE runs on 5001-5006, HTTP /call runs on 5101-5106
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

# ── MCP HTTP client ────────────────────────────────────────────────────────

async def call_tool(tool_name: str, tool_input: dict) -> str:
    """
    Call a local MCP server tool via HTTP POST.
    Returns the tool result as a string (same format MCP servers return).
    Falls back to inline execution if the MCP server is unreachable.
    """
    base_url = MCP_SERVER_URLS.get(tool_name)
    if not base_url:
        return json.dumps({"error": f"No MCP server registered for tool: {tool_name}"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # MCP servers expose tools at /call endpoint
            response = await client.post(
                f"{base_url}/call",
                json={
                    "tool": tool_name,
                    "input": tool_input,
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            # MCP servers return {"result": "..."} or {"error": "..."}
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


async def _fallback(tool_name: str, tool_input: dict) -> str:
    """
    Inline fallback if MCP server is down.
    Keeps the app working during development even if a server crashes.
    """
    from services.patient_lookup import search_patient as find_patient
    from services.fhir_client import create_patient

from datetime import date, timedelta

from datetime import date, timedelta
import random

def _get_slots():
    """Generate slots dynamically for the next 10 weekdays."""
    today = date.today()
    weekdays = []
    d = today + timedelta(days=1)
    while len(weekdays) < 10:
        if d.weekday() < 5:
            weekdays.append(d)
        d += timedelta(days=1)

    day_names  = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    months     = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]

    def fmt(d):
        return f"{day_names[d.weekday()]} {months[d.month-1]} {d.day}"

    slots = [
        {"id": "s1",  "doctor": "Dr. Patel",   "specialty": "Family Medicine", "date": fmt(weekdays[0]), "time": "9:00 AM",  "day": weekdays[0].strftime("%A").lower()},
        {"id": "s2",  "doctor": "Dr. Patel",   "specialty": "Family Medicine", "date": fmt(weekdays[0]), "time": "11:30 AM", "day": weekdays[0].strftime("%A").lower()},
        {"id": "s3",  "doctor": "Dr. Patel",   "specialty": "Family Medicine", "date": fmt(weekdays[2]), "time": "1:00 PM",  "day": weekdays[2].strftime("%A").lower()},
        {"id": "s4",  "doctor": "Dr. Chen",    "specialty": "Family Medicine", "date": fmt(weekdays[3]), "time": "8:30 AM",  "day": weekdays[3].strftime("%A").lower()},
        {"id": "s5",  "doctor": "Dr. Chen",    "specialty": "Family Medicine", "date": fmt(weekdays[4]), "time": "10:00 AM", "day": weekdays[4].strftime("%A").lower()},
        {"id": "s6",  "doctor": "Dr. Okafor",  "specialty": "OB/GYN",          "date": fmt(weekdays[0]), "time": "2:00 PM",  "day": weekdays[0].strftime("%A").lower()},
        {"id": "s7",  "doctor": "Dr. Okafor",  "specialty": "OB/GYN",          "date": fmt(weekdays[3]), "time": "9:30 AM",  "day": weekdays[3].strftime("%A").lower()},
        {"id": "s8",  "doctor": "Dr. Kim",     "specialty": "Cardiology",      "date": fmt(weekdays[1]), "time": "3:00 PM",  "day": weekdays[1].strftime("%A").lower()},
        {"id": "s9",  "doctor": "Dr. Kim",     "specialty": "Cardiology",      "date": fmt(weekdays[4]), "time": "8:00 AM",  "day": weekdays[4].strftime("%A").lower()},
        {"id": "s10", "doctor": "Dr. Rivera",  "specialty": "Urgent Care",     "date": fmt(weekdays[0]), "time": "10:00 AM", "day": weekdays[0].strftime("%A").lower()},
        {"id": "s11", "doctor": "Dr. Rivera",  "specialty": "Urgent Care",     "date": fmt(weekdays[1]), "time": "3:30 PM",  "day": weekdays[1].strftime("%A").lower()},
        {"id": "s12", "doctor": "Dr. Santos",  "specialty": "Mental Health",   "date": fmt(weekdays[2]), "time": "11:00 AM", "day": weekdays[2].strftime("%A").lower()},
        {"id": "s13", "doctor": "Dr. Santos",  "specialty": "Mental Health",   "date": fmt(weekdays[5]), "time": "2:00 PM",  "day": weekdays[5].strftime("%A").lower()},
        {"id": "s14", "doctor": "Dr. Adams",   "specialty": "Dermatology",     "date": fmt(weekdays[3]), "time": "9:00 AM",  "day": weekdays[3].strftime("%A").lower()},
        {"id": "s15", "doctor": "Dr. Wong",    "specialty": "Pediatrics",      "date": fmt(weekdays[1]), "time": "2:30 PM",  "day": weekdays[1].strftime("%A").lower()},
        {"id": "s16", "doctor": "Dr. Wong",    "specialty": "Pediatrics",      "date": fmt(weekdays[4]), "time": "8:00 AM",  "day": weekdays[4].strftime("%A").lower()},
        {"id": "s17", "doctor": "Dr. Patel",   "specialty": "Family Medicine", "date": fmt(weekdays[6]), "time": "9:00 AM",  "day": weekdays[6].strftime("%A").lower()},
        {"id": "s18", "doctor": "Dr. Chen",    "specialty": "Family Medicine", "date": fmt(weekdays[7]), "time": "11:00 AM", "day": weekdays[7].strftime("%A").lower()},
        {"id": "s19", "doctor": "Dr. Kim",     "specialty": "Cardiology",      "date": fmt(weekdays[8]), "time": "10:00 AM", "day": weekdays[8].strftime("%A").lower()},
        {"id": "s20", "doctor": "Dr. Santos",  "specialty": "Mental Health",   "date": fmt(weekdays[9]), "time": "3:00 PM",  "day": weekdays[9].strftime("%A").lower()},
    ]
    return slots

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
        if tool_name == "lookup_patient":
            record = find_patient(
                name=tool_input.get("name"),
                dob=tool_input.get("dob") or None,
                #phone=tool_input.get("phone") or None,
            )
            return json.dumps(record) if record else "NOT_FOUND"

        if tool_name == "check_eligibility":
            result = check_eligibility_mock(
                insurance_id=tool_input.get("insurance_id", ""),
                payer=tool_input.get("payer", ""),
            )
            return json.dumps(result)
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
            return json.dumps({
                "slots": [],
                "message": f"No slots available on {filter_day.capitalize()} for {dept}.",
                "available_days": list(set(s["day"].capitalize() for s in matched))
            })

    # Filter by time if requested (after a certain hour)
        if filter_time:
            try:
                # Parse "after 2pm" or "afternoon" etc.
                if "afternoon" in filter_time or "pm" in filter_time:
                    hour_cutoff = 12
                    if "2" in filter_time: hour_cutoff = 14
                    elif "3" in filter_time: hour_cutoff = 15
                    elif "4" in filter_time: hour_cutoff = 16
                elif "morning" in filter_time or "am" in filter_time:
                    hour_cutoff = 0
                else:
                    hour_cutoff = 0

                def slot_hour(t):
                    h = int(t.split(":")[0])
                    if "PM" in t and h != 12: h += 12
                    return h

                time_filtered = [s for s in matched if slot_hour(s["time"]) >= hour_cutoff]
                if time_filtered:
                    matched = time_filtered
                else:
                    return json.dumps({
                        "slots": [],
                        "message": f"No slots after {filter_time} for {dept}.",
                        "available_times": [s["time"] for s in matched[:5]]
                    })
            except Exception:
                pass

        return json.dumps({"slots": matched, "message": "available"})

        if tool_name == "fhir_create_patient":
            fhir_id = create_patient(tool_input)
            return json.dumps({"fhir_id": fhir_id or "pending", "status": "created"})

    except Exception as e:
        print(f"[mcp_client] fallback failed for {tool_name}: {e}")
        return json.dumps({"error": str(e)})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def call_tool_sync(tool_name: str, tool_input: dict) -> str:
    """Sync wrapper for use in non-async contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context — use asyncio.create_task pattern
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, call_tool(tool_name, tool_input))
                return future.result()
        return loop.run_until_complete(call_tool(tool_name, tool_input))
    except Exception as e:
        return json.dumps({"error": str(e)})