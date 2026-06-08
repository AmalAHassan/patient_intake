"""
MCP Server — Epic FHIR (Stub)
Same interface as hapi_fhir/server.py.
Returns not_connected until Epic sandbox access is approved.
Runs on port 5004.

TO ACTIVATE:
1. Get Epic sandbox access at fhir.epic.com
2. Set EPIC_CLIENT_ID and EPIC_PRIVATE_KEY in .env
3. Replace stub returns below with real Epic FHIR API calls
4. Change EHR_BACKEND=epic in .env
"""
import json
import os
import sys

# Use MCP_BACKEND_DIR if set by start_mcp_servers.py, else resolve from file location
BACKEND_DIR = os.environ.get(
    "MCP_BACKEND_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
for env_path in [os.path.join(BACKEND_DIR, ".env"), os.path.join(BACKEND_DIR, "..", ".env")]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

from fastmcp import FastMCP

mcp = FastMCP("epic-fhir")

NOT_CONNECTED = json.dumps({
    "status": "not_connected",
    "ehr": "epic",
    "message": "Epic sandbox access pending. Set EPIC_CLIENT_ID and EPIC_PRIVATE_KEY in .env to activate.",
})


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
    """Create a patient in Epic FHIR. NOT YET CONNECTED."""
    # TODO: implement Epic FHIR R4 Patient create via SMART on FHIR / OAuth2
    # POST {epic_base_url}/api/FHIR/R4/Patient
    return NOT_CONNECTED


@mcp.tool
def fhir_get_patient(patient_id: str) -> str:
    """Get a patient from Epic FHIR by ID. NOT YET CONNECTED."""
    # TODO: GET {epic_base_url}/api/FHIR/R4/Patient/{patient_id}
    return NOT_CONNECTED


@mcp.tool
def fhir_get_slots(department: str) -> str:
    """Get available slots from Epic scheduling. NOT YET CONNECTED."""
    # TODO: GET {epic_base_url}/api/FHIR/R4/Slot?service-type={department}
    return NOT_CONNECTED


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=5004)