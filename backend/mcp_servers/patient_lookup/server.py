"""
MCP Server — Patient Lookup
Wraps services/patient_lookup.py as an MCP tool.
Runs on port 5001.
"""
import sys
import os
import json

# Resolve backend/ directory absolutely from this file's location
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

# Import after path is set
import importlib
pl = importlib.import_module("services.patient_lookup")
find_patient = pl.find_patient
load_patients = pl.load_patients

load_patients()

mcp = FastMCP("patient-lookup")


@mcp.tool
def lookup_patient(name: str, dob: str = "", phone: str = "") -> str:
    """
    Look up a patient in the practice database.
    Call as soon as you have the patient's name plus EITHER their
    date of birth OR their phone number.
    Returns the matching patient record or NOT_FOUND.
    """
    record = find_patient(name=name, dob=dob or None, phone=phone or None)
    if not record:
        return "NOT_FOUND"
    return json.dumps(record)


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=5001)