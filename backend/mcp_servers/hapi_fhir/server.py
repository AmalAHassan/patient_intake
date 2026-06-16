"""
MCP Server — HAPI FHIR (Default EHR)
Wraps fhir_client.py as MCP tools.
Runs on port 5003.
"""
import sys
import os
import json

# Use MCP_BACKEND_DIR if set by start_mcp_servers.py, else resolve from file location
BACKEND_DIR = os.environ.get(
    "MCP_BACKEND_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)
sys.path.insert(0, BACKEND_DIR)

# Load .env — check both backend/ and project root
from dotenv import load_dotenv
for env_path in [
    os.path.join(BACKEND_DIR, ".env"),
    os.path.join(BACKEND_DIR, "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

from fastmcp import FastMCP

# Import services after env is loaded
import importlib
fc = importlib.import_module("services.fhir_client")
create_patient = fc.create_patient
get_patient = fc.get_patient

mcp = FastMCP("hapi-fhir")


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
        "name": name,
        "dob": dob,
        "phone": phone,
        "email": email,
        "insurance_id": insurance_id,
        "payer": payer,
        "department": department,
        "reason": reason,
        "appointment_doctor": appointment_doctor,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
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
def fhir_get_slots(department: str) -> str:
    """
    Get available appointment slots for a department.
    Currently hardcoded — wire to FHIR Slot resources later.
    """
    SLOTS = [
        {"id": "s1",  "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": "Mon Jun 9",  "time": "9:00 AM"},
        {"id": "s2",  "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": "Mon Jun 9",  "time": "11:30 AM"},
        {"id": "s3",  "doctor": "Dr. Patel",  "specialty": "Family Medicine", "date": "Tue Jun 10", "time": "1:00 PM"},
        {"id": "s4",  "doctor": "Dr. Chen",   "specialty": "Family Medicine", "date": "Tue Jun 10", "time": "8:30 AM"},
        {"id": "s5",  "doctor": "Dr. Chen",   "specialty": "Family Medicine", "date": "Wed Jun 11", "time": "10:00 AM"},
        {"id": "s6",  "doctor": "Dr. Okafor", "specialty": "OB/GYN",         "date": "Mon Jun 9",  "time": "2:00 PM"},
        {"id": "s7",  "doctor": "Dr. Okafor", "specialty": "OB/GYN",         "date": "Thu Jun 12", "time": "9:30 AM"},
        {"id": "s8",  "doctor": "Dr. Kim",    "specialty": "Cardiology",      "date": "Wed Jun 11", "time": "3:00 PM"},
        {"id": "s9",  "doctor": "Dr. Kim",    "specialty": "Cardiology",      "date": "Fri Jun 13", "time": "8:00 AM"},
        {"id": "s10", "doctor": "Dr. Rivera", "specialty": "Urgent Care",     "date": "Mon Jun 9",  "time": "10:00 AM"},
        {"id": "s11", "doctor": "Dr. Rivera", "specialty": "Urgent Care",     "date": "Mon Jun 9",  "time": "3:30 PM"},
        {"id": "s12", "doctor": "Dr. Santos", "specialty": "Mental Health",   "date": "Thu Jun 12", "time": "11:00 AM"},
        {"id": "s13", "doctor": "Dr. Adams",  "specialty": "Dermatology",     "date": "Fri Jun 13", "time": "9:00 AM"},
        {"id": "s14", "doctor": "Dr. Wong",   "specialty": "Pediatrics",      "date": "Tue Jun 10", "time": "2:30 PM"},
        {"id": "s15", "doctor": "Dr. Wong",   "specialty": "Pediatrics",      "date": "Wed Jun 11", "time": "8:00 AM"},
    ]
    dept_lower = department.lower()
    matched = [s for s in SLOTS if dept_lower in s["specialty"].lower()]
    return json.dumps(matched if matched else SLOTS[:3])



# ── HTTP /call endpoint for mcp_client.py ─────────────────────────────────
# This lets FastAPI call tools directly without going through Anthropic.
# When deploying with remote MCP, this endpoint is no longer needed.
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn as _uvicorn

http_app = FastAPI()

@http_app.post("/call")
async def call_tool_http(request: Request):
    body = await request.json()
    tool_name  = body.get("tool")
    tool_input = body.get("input", {})
    try:
        # Call the tool function directly by name
        tool_fn = globals().get(tool_name)
        if not tool_fn:
            return JSONResponse({"error": f"Tool not found: {tool_name}"}, status_code=404)
        result = tool_fn(**tool_input)
        return JSONResponse({"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

if __name__ == "__main__":
    import threading, uvicorn as _uv

    # Run HTTP /call server on port 5103
    def run_http():
        _uv.run(http_app, host="127.0.0.1", port=5103, log_level="error")

    threading.Thread(target=run_http, daemon=True).start()

    # Run MCP SSE server on port 5003
    mcp.run(transport="sse", host="127.0.0.1", port=5003)