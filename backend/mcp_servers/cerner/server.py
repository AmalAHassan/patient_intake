"""
MCP Server — Oracle Cerner (Stub)
Same interface as hapi_fhir/server.py.
Runs on port 5006.

TO ACTIVATE:
1. Get API access at code.cerner.com
2. Set CERNER_CLIENT_ID and CERNER_CLIENT_SECRET in .env
3. Replace stub returns with real Cerner Ignite FHIR R4 calls
4. Change EHR_BACKEND=cerner in .env
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

mcp = FastMCP("cerner-fhir")

NOT_CONNECTED = json.dumps({
    "status": "not_connected",
    "ehr": "cerner",
    "message": "Cerner sandbox access pending. Set CERNER_CLIENT_ID in .env to activate.",
})


@mcp.tool
def fhir_create_patient(
    name: str, dob: str, phone: str = "", email: str = "",
    insurance_id: str = "", payer: str = "", department: str = "",
    reason: str = "", appointment_doctor: str = "",
    appointment_date: str = "", appointment_time: str = "",
) -> str:
    """Create a patient in Cerner. NOT YET CONNECTED."""
    # TODO: POST {cerner_base_url}/Patient via Cerner Ignite FHIR R4
    return NOT_CONNECTED


@mcp.tool
def fhir_get_patient(patient_id: str) -> str:
    """Get a patient from Cerner by ID. NOT YET CONNECTED."""
    return NOT_CONNECTED


@mcp.tool
def fhir_get_slots(department: str) -> str:
    """Get available slots from Cerner scheduling. NOT YET CONNECTED."""
    return NOT_CONNECTED


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=5006)