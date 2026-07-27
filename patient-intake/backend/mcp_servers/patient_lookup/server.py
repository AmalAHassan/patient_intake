"""
MCP Server — Patient Lookup
Wraps services/patient_lookup.py as an MCP tool.
Runs on port 5001.
"""
import sys
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn as _uvicorn
from fastmcp import FastMCP
import importlib


BACKEND_DIR = os.environ.get(
    "MCP_BACKEND_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
for env_path in [
    os.path.join(BACKEND_DIR, ".env"),
    os.path.join(BACKEND_DIR, "..", ".env"),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break


pl = importlib.import_module("services.patient_lookup")
find_patient  = pl.search_patient
load_patients = pl.load_patients
load_patients()

mcp = FastMCP("patient-lookup")


def _lookup_patient(name: str, dob: str = "") -> str:
    record = find_patient(name=name, dob=dob or "")
    if not record:
        return "NOT_FOUND"
    return json.dumps(record)


@mcp.tool
def lookup_patient(name: str, dob: str = "") -> str:
    """
    Look up a patient in the practice database.
    Call as soon as you have the patient's name and date of birth.
    Returns the matching patient record or NOT_FOUND.
    """
    return _lookup_patient(name=name, dob=dob)


http_app = FastAPI()

@http_app.post("/call")
async def call_tool_http(request: Request):
    body = await request.json()
    tool_name  = body.get("tool")
    tool_input = body.get("input", {})
    try:
        if tool_name == "lookup_patient":
            result = _lookup_patient(
                name=tool_input.get("name", ""),
                dob=tool_input.get("dob", ""),
            )
            return JSONResponse({"result": result})
        return JSONResponse({"error": f"Tool not found: {tool_name}"}, status_code=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import threading
    import uvicorn as _uv

    def run_http():
        _uv.run(http_app, host="0.0.0.0", port=5101, log_level="error")

    threading.Thread(target=run_http, daemon=True).start()
    mcp.run(transport="sse", host="0.0.0.0", port=5001)