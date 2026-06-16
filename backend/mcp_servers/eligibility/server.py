"""
MCP Server — Insurance Eligibility
Mock by default. Swap USE_MOCK_ELIGIBILITY=false in .env to use real Availity.
Runs on port 5002.
"""
import sys
import os

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
import json
import time
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from fastmcp import FastMCP

mcp = FastMCP("eligibility")

# ── Mock responses — covers all real scenarios you need to test ──
MOCK_RESPONSES = {
    "active": {
        "covered": True,
        "status": "active",
        "plan": "PPO",
        "copay": 25.00,
        "deductible": 1500.00,
        "deductible_met": 400.00,
        "out_of_pocket_max": 5000.00,
        "out_of_pocket_met": 400.00,
        "effective_date": "2024-01-01",
        "term_date": "2026-12-31",
    },
    "inactive": {
        "covered": False,
        "status": "inactive",
        "message": "Policy terminated 2025-12-31",
    },
    "hdhp": {
        "covered": True,
        "status": "active",
        "plan": "HDHP",
        "copay": 0.00,
        "deductible": 5000.00,
        "deductible_met": 0.00,
        "out_of_pocket_max": 7000.00,
        "out_of_pocket_met": 0.00,
    },
    "medicare": {
        "covered": True,
        "status": "active",
        "plan": "Medicare Part B",
        "copay": 20.00,
        "deductible": 240.00,
        "deductible_met": 240.00,
    },
    "not_found": {
        "covered": False,
        "status": "not_found",
        "message": "Member ID not found with this payer",
    },
}

# Token cache for real Availity calls
_token_cache: dict = {"token": None, "expires_at": 0}


def _get_availity_token() -> str:
    """Fetch or return cached Availity OAuth2 token."""
    if time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["token"]

    import requests
    response = requests.post(
        "https://tst.api.availity.com/v1/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("AVAILITY_CLIENT_ID"),
            "client_secret": os.getenv("AVAILITY_CLIENT_SECRET"),
        },
        timeout=10,
    )
    response.raise_for_status()
    token_data = response.json()
    _token_cache["token"] = token_data["access_token"]
    _token_cache["expires_at"] = time.time() + 300
    return _token_cache["token"]


def _check_availity_real(insurance_id: str, payer: str, dob: str) -> dict:
    """Real Availity X12 270/271 eligibility check via REST wrapper."""
    import requests
    token = _get_availity_token()
    response = requests.post(
        "https://tst.api.availity.com/availity/development-partner/v1/coverages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"memberId": insurance_id, "payerId": payer, "dateOfBirth": dob},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _check_mock(insurance_id: str, payer: str) -> dict:
    """Return mock response based on insurance_id prefix or payer name."""
    if not insurance_id or insurance_id == "NONE":
        result = MOCK_RESPONSES["not_found"].copy()
    elif "medicare" in payer.lower():
        result = MOCK_RESPONSES["medicare"].copy()
    elif insurance_id.upper().startswith("HDHP"):
        result = MOCK_RESPONSES["hdhp"].copy()
    elif insurance_id.upper().startswith("TERM"):
        result = MOCK_RESPONSES["inactive"].copy()
    else:
        result = MOCK_RESPONSES["active"].copy()

    result["payer"] = payer
    result["member_id"] = insurance_id
    return result


@mcp.tool
def check_eligibility(insurance_id: str, payer: str, dob: str = "") -> str:
    """
    Check insurance eligibility for a patient.
    Returns coverage status, copay, deductible, and plan details.
    Uses mock data by default. Set USE_MOCK_ELIGIBILITY=false in .env for real Availity.
    """
    use_mock = os.getenv("USE_MOCK_ELIGIBILITY", "true").lower() == "true"

    if use_mock:
        result = _check_mock(insurance_id, payer)
    else:
        try:
            result = _check_availity_real(insurance_id, payer, dob)
        except Exception as e:
            # Fall back to mock if real call fails during development
            result = _check_mock(insurance_id, payer)
            result["warning"] = f"Availity call failed, using mock: {str(e)}"

    return json.dumps(result)



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

    # Run HTTP /call server on port 5102
    def run_http():
        _uv.run(http_app, host="127.0.0.1", port=5102, log_level="error")

    threading.Thread(target=run_http, daemon=True).start()

    # Run MCP SSE server on port 5002
    mcp.run(transport="sse", host="127.0.0.1", port=5002)