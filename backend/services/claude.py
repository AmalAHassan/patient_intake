"""
claude.py — Conversational intake loop.

SYSTEM_PROMPT = conversation flow only (steps 1-8, JSON format, validation)
AGENT_GUIDELINES.md = clinical rules, emergency handling, behavior rules

Tool calls route through mcp_client.py → local MCP servers.

To switch to remote MCP (ngrok or deployed):
  1. Update MCP_SERVERS list below with public URLs
  2. Swap messages.create() to beta.messages.create(mcp_servers=MCP_SERVERS)
  3. Remove tools=TOOLS and the tool execution loop
"""
import json
import os
import asyncio
import pathlib
import redis
import httpx
from anthropic import Anthropic
from config import settings
from services.mcp_client import call_tool

CRISIS_NOTIFIER_URL = os.getenv("CRISIS_NOTIFIER_URL", "http://localhost:8001")

redis_client     = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

MODEL              = "claude-haiku-4-5"
MAX_TOOL_ITERATIONS = 10
MAX_LOOKUP_RETRIES  = 3

# ── Remote MCP server list (used when switching to beta.messages.create) ───
# Update these URLs when using ngrok or deploying
MCP_SERVERS = [
    {"type": "url", "url": os.getenv("MCP_PATIENT_LOOKUP_URL", "http://localhost:5001/sse"), "name": "patient-lookup"},
    {"type": "url", "url": os.getenv("MCP_ELIGIBILITY_URL",    "http://localhost:5002/sse"), "name": "eligibility"},
    {"type": "url", "url": os.getenv("MCP_EHR_URL",            "http://localhost:5003/sse"), "name": "ehr"},
]

# ── Tool schema (used with local routing via mcp_client) ───────────────────
TOOLS = [
    {
        "name": "lookup_patient",
        "description": "Look up a patient by name + DOB. Returns record or NOT_FOUND.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":  {"type": "string"},
                "dob":   {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "check_eligibility",
        "description": "Check insurance eligibility. Returns coverage status and copay.",
        "input_schema": {
            "type": "object",
            "properties": {
                "insurance_id": {"type": "string"},
                "payer":        {"type": "string"},
            },
            "required": ["insurance_id", "payer"],
        },
    },
    {
        "name": "fhir_get_slots",
        "description": "Get available appointment slots for a department.",
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
            },
            "required": ["department"],
        },
    },
    {
        "name": "fhir_create_patient",
        "description": "Save the completed patient record to FHIR. Call at the end of intake.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":               {"type": "string"},
                "dob":                {"type": "string"},
                "phone":              {"type": "string"},
                "email":              {"type": "string"},
                "insurance_id":       {"type": "string"},
                "payer":              {"type": "string"},
                "department":         {"type": "string"},
                "reason":             {"type": "string"},
                "appointment_doctor": {"type": "string"},
                "appointment_date":   {"type": "string"},
                "appointment_time":   {"type": "string"},
            },
            "required": ["name", "dob"],
        },
    },
]

# ── Load clinical guidelines ───────────────────────────────────────────────
def _load_guidelines() -> str:
    for path in [
        pathlib.Path(__file__).parent.parent.parent / "AGENT_GUIDELINES.md",
        pathlib.Path(__file__).parent.parent / "AGENT_GUIDELINES.md",
    ]:
        if path.exists():
            return "\n\n---\nCLINICAL GUIDELINES (follow these exactly):\n" + path.read_text()
    return ""

# ── System prompt — conversation flow only ────────────────────────────────
# Clinical rules, emergency handling, and behavior rules live in
# AGENT_GUIDELINES.md and are appended at runtime via _load_guidelines().
SYSTEM_PROMPT = """You are a friendly front-desk medical receptionist AI.
Speak in short natural sentences. One question per turn. Never ask more than one question at a time.
When the user says "begin" respond with your opening greeting only.

STEP 1 — NEW OR RETURNING
Your very first message must always be:
"Hi, welcome! Are you a new patient or a returning patient?"
Wait for their answer before doing anything else.

STEP 2 — IDENTITY

RETURNING patient:
  Ask for full name, then date of birth (MM/DD/YYYY) only.
  As soon as you have name + DOB, call `lookup_patient`.
  If record found:
    - Show only city and state: "I found a record — can you confirm the city and state we have on file?"
    - If match: go to STEP 3.
    - If no match: ask for zip code as secondary check.
    - If zip also fails: output {"status": "staff_requested"}
  If NOT_FOUND:
    - Offer retry or new patient registration. Max 3 retries.
  If match_count > 1:
    - Ask for zip code to narrow down. Max 3 retries.

NEW patient:
  Collect one at a time: full name → DOB (MM/DD/YYYY) → phone → email.
  Validate each field using the rules in CLINICAL GUIDELINES before accepting.
  Then go to STEP 3.

STEP 3 — CONFIRM DETAILS
RETURNING: confirm phone (last 4 digits only) and email on file. Update if changed.
NEW: skip to STEP 4.

STEP 4 — INSURANCE
RETURNING: confirm insurance on file. Call `check_eligibility`. Share copay result.
NEW: ask for payer name and member ID. Call `check_eligibility`. Share copay result.
     If self-pay: set payer="Self-pay", insurance_id="NONE". Skip eligibility check.
     Always use EXACTLY what the patient typed for payer name — never rename it.

STEP 5 — DEPARTMENT
Ask: "Which department are you visiting today?"
Options: 1. Family Medicine  2. OB/GYN  3. Cardiology  4. Urgent Care
         5. Mental Health    6. Dermatology  7. Pediatrics  8. Other

STEP 6 — REASON FOR VISIT
Ask: "Briefly describe why you're coming in today — your doctor will see this before your appointment."
Accept free text exactly as typed.
Then immediately run the EMERGENCY CHECK and DEPARTMENT ALIGNMENT CHECK
defined in CLINICAL GUIDELINES before proceeding.

STEP 7 — SCHEDULING
Call `fhir_get_slots` with the chosen department.
Present slots numbered, one per line. Wait for patient to pick a number.

STEP 8 — SAVE AND COMPLETE
Call `fhir_create_patient` with all collected fields.
Say: "Perfect! You're booked with [doctor] on [date] at [time]. You're all set — see you soon! ✓"

Then output ONLY this JSON on a new line:
{"status": "complete", "data": {"name": "", "dob": "", "phone": "", "email": "", "insurance_id": "", "payer": "", "copay": "", "department": "", "reason": "", "appointment_doctor": "", "appointment_date": "", "appointment_time": ""}}

After any completion or redirect, if the patient says anything else reply with:
{"status": "ended"}
"""


# ── Crisis alert ───────────────────────────────────────────────────────────
async def _send_crisis_alert(
    session_id: str,
    alert_type: str,
    reason: str,
    client_ip: str = "unknown"
):
    patient_name    = "unknown"
    patient_address = "unknown"
    try:
        collected_json = redis_client.get(f"session:{session_id}:collected")
        if collected_json:
            c = json.loads(collected_json)
            patient_name    = c.get("name", "unknown")
            patient_address = c.get("address", "unknown")
        if patient_name == "unknown":
            history_json = redis_client.get(f"session:{session_id}:history")
            if history_json:
                for msg in json.loads(history_json):
                    if isinstance(msg.get("content"), list):
                        for block in msg["content"]:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                try:
                                    data = json.loads(block.get("content", "{}"))
                                    if isinstance(data, dict) and data.get("name"):
                                        patient_name    = data.get("name", "unknown")
                                        patient_address = data.get("address", "unknown")
                                except Exception:
                                    pass
    except Exception as e:
        print(f"[crisis] Could not extract patient info: {e}")

    payload = {
        "type":            alert_type,
        "session_id":      session_id,
        "patient_name":    patient_name,
        "patient_address": patient_address,
        "client_ip":       client_ip,
        "reason":          reason if isinstance(reason, str) else str(reason),
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{CRISIS_NOTIFIER_URL}/alert", json=payload)
            print(f"[crisis] Alert sent: {alert_type} — {patient_name}")
    except Exception as e:
        print(f"[crisis] Could not reach notifier: {e}")


# ── Main chat loop ─────────────────────────────────────────────────────────
async def chat(session_id: str, user_message: str, client_ip: str = "unknown") -> dict:
    history_key   = f"session:{session_id}:history"
    collected_key = f"session:{session_id}:collected"

    history_json = redis_client.get(history_key)
    history      = json.loads(history_json) if history_json else []

    history.append({"role": "user", "content": "begin" if user_message == "__start__" else user_message})

    assistant_text = ""
    lookup_count   = 0
    system         = SYSTEM_PROMPT + _load_guidelines()

    for _ in range(MAX_TOOL_ITERATIONS):

        # ── LOCAL routing (current) ────────────────────────────────────────
        # Tools schema sent to Claude; mcp_client routes execution to MCP servers
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=system,
            tools=TOOLS,
            messages=history,
        )

        # # ── REMOTE MCP (swap when ngrok/deployed) ─────────────────────────
        # response = anthropic_client.beta.messages.create(
        #     model=MODEL,
        #     max_tokens=800,
        #     system=system,
        #     messages=history,
        #     mcp_servers=MCP_SERVERS,
        #     betas=["mcp-client-2025-04-04"],
        # )

        if response.stop_reason != "tool_use":
            assistant_text = "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            history.append({"role": "assistant", "content": assistant_text})
            break

        for block in response.content:
            if getattr(block, "name", "") == "lookup_patient":
                lookup_count += 1

        history.append({"role": "assistant", "content": [_block_to_dict(b) for b in response.content]})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "lookup_patient" and lookup_count > MAX_LOOKUP_RETRIES:
                content = "MAX_RETRIES_EXCEEDED — tell the patient a staff member will assist them."
            else:
                content = await call_tool(block.name, block.input)
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     content,
            })

        history.append({"role": "user", "content": tool_results})

    redis_client.setex(history_key, 86400, json.dumps(history))

    result = {"reply": assistant_text, "status": "collecting", "data": None}

    if '{"status": "emergency_redirect"}' in assistant_text:
        friendly = assistant_text[:assistant_text.find('{"status": "emergency_redirect"}')].strip()
        result.update({"reply": friendly, "status": "emergency_redirect"})
        text_lower = assistant_text.lower()
        is_crisis  = any(kw in text_lower for kw in ["988", "suicidal", "self-harm"])
        asyncio.create_task(_send_crisis_alert(
            session_id=session_id,
            alert_type="mental_health_crisis" if is_crisis else "medical_emergency",
            reason=history[-2]["content"] if len(history) >= 2 else "unknown",
            client_ip=client_ip,
        ))
        return result

    if '{"status": "staff_requested"}' in assistant_text:
        friendly = assistant_text[:assistant_text.find('{"status": "staff_requested"}')].strip()
        result.update({"reply": friendly, "status": "staff_requested"})
        return result

    if '{"status": "complete"' in assistant_text:
        try:
            json_str = assistant_text[assistant_text.find('{"status": "complete"'):]
            parsed   = json.loads(json_str)
            if parsed.get("status") == "complete":
                data = parsed.get("data", {})
                for f in ["department","copay","appointment_doctor","appointment_date","appointment_time"]:
                    data.setdefault(f, "")
                friendly = assistant_text[:assistant_text.find('{"status": "complete"')].strip()
                if not friendly:
                    friendly = (
                        f"Perfect! You're booked with {data.get('appointment_doctor','your doctor')}"
                        f" on {data.get('appointment_date','')} at {data.get('appointment_time','')}."
                        " You're all set — see you soon! ✓"
                    )
                result.update({"reply": friendly, "status": "complete", "data": data})
                redis_client.setex(collected_key, 86400, json.dumps(data))
        except json.JSONDecodeError:
            pass

    return result


def _block_to_dict(block) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": block.type}


async def get_session_data(session_id: str) -> dict:
    data_json = redis_client.get(f"session:{session_id}:collected")
    return json.loads(data_json) if data_json else {}