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

    # Run HTTP /call server on port 5101
    def run_http():
        _uv.run(http_app, host="127.0.0.1", port=5101, log_level="error")

    threading.Thread(target=run_http, daemon=True).start()

    # Run MCP SSE server on port 5001
    mcp.run(transport="sse", host="127.0.0.1", port=5001)