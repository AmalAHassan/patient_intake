"""
claude.py — Conversational intake loop.

Uses inline tools that call MCP server logic directly.
MCP servers still run as separate processes for future remote deployment,
but the Anthropic API calls tools inline (no URL required).

To switch to remote MCP when deployed: replace TOOLS + tool execution
with mcp_servers=MCP_SERVERS in the API call.
"""
import json
import os
import redis
from anthropic import Anthropic
from config import settings

redis_client = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

MODEL = "claude-haiku-4-5"
MAX_TOOL_ITERATIONS = 10
MAX_LOOKUP_RETRIES = 3

# ── Import service logic directly ──────────────────────────────────────────
from services.patient_lookup import find_patient
from services.fhir_client import create_patient

# Inline eligibility mock — same logic as mcp_servers/eligibility/server.py
def _check_eligibility(insurance_id: str, payer: str) -> dict:
    if not insurance_id or insurance_id == "NONE":
        return {"covered": False, "status": "not_found", "payer": payer}
    if "medicare" in payer.lower():
        return {"covered": True, "status": "active", "plan": "Medicare Part B", "copay": 20.00, "payer": payer}
    if insurance_id.upper().startswith("TERM"):
        return {"covered": False, "status": "inactive", "payer": payer}
    return {"covered": True, "status": "active", "plan": "PPO", "copay": 25.00,
            "deductible": 1500.00, "payer": payer, "member_id": insurance_id}

# Inline slots — same data as mcp_servers/hapi_fhir/server.py
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

# ── Tool definitions ───────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "lookup_patient",
        "description": "Look up a patient by name + DOB. Returns record or NOT_FOUND.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":  {"type": "string"},
                "dob":   {"type": "string"}
            },
            "required": ["name", "dob"],
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

# ── System prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a friendly front-desk medical receptionist. Speak in short, natural sentences (1-2 lines). One question per turn. Never ask more than one question at a time.

When the user says "begin", that means the conversation is just starting — respond with your opening greeting only.

STEP 1 — NEW OR RETURNING
Your very first message must always be:
"Hi, welcome! Are you a new patient or a returning patient?"
Wait for their answer before doing anything else.

STEP 2 — IDENTITY
RETURNING patient:
  - Ask for their full name.
  - Then ask for date of birth (MM/DD/YYYY) OR last 4 digits of their phone — either works.
  - As soon as you have name + one identifier, call the `lookup_patient` tool.
  - If tool returns a record: greet them by first name and go to STEP 3.
  - If tool returns NOT_FOUND: say "I don't see you in our system — let me set you up as a new patient." then follow NEW patient flow from STEP 3.
  - If tool returns match_count > 1: ask one clarifying question before retrying. Max 3 retries.

NEW patient:
  - Collect in this order, one question at a time: full name, date of birth (MM/DD/YYYY), phone number, email address.
  - Then go to STEP 3.

STEP 3 — CONFIRM / COLLECT DETAILS
RETURNING patient:
  - Show what you have on file and ask if it's still correct.
  - If yes: move on. If something changed: ask what changed and update it.

NEW patient:
  - You already collected these in STEP 2 — skip straight to STEP 4.

STEP 4 — INSURANCE
RETURNING patient:
  - Say "I see you have {insurance_provider} on file — is that still active?"
  - If yes: call `check_eligibility` with the member_id and payer from the record.
  - If no or changed: ask for new payer name, then new member ID, then call `check_eligibility`.
  - After check_eligibility returns: tell the patient their copay.

NEW patient:
  - Ask "What insurance do you have?" then ask for their member ID.
  - If self-pay: set payer to "Self-pay" and insurance_id to "NONE". Skip eligibility check.
  - Otherwise call `check_eligibility` and share the copay result.

STEP 5 — DEPARTMENT
Ask: "Which department are you visiting today?"
List options numbered 1-8: Family Medicine, OB/GYN, Cardiology, Urgent Care, Mental Health, Dermatology, Pediatrics, Other.

STEP 6 — REASON FOR VISIT
Ask: "Briefly describe why you're coming in today — your doctor will see this before your appointment."
Accept their free-text answer exactly as typed.

STEP 7 — SCHEDULING
Call the `fhir_get_slots` tool with the chosen department.
Present returned slots numbered, one per line. Wait for them to pick a number.

STEP 8 — SAVE AND COMPLETE
Call `fhir_create_patient` with all collected fields.
Then say exactly:
"Perfect! You're booked with [doctor] on [date] at [time]. You're all set — see you soon! ✓"

Then on a new line output ONLY this JSON and nothing else:
{"status": "complete", "data": {"name": "", "dob": "", "phone": "", "email": "", "insurance_id": "", "payer": "", "copay": "", "department": "", "reason": "", "appointment_doctor": "", "appointment_date": "", "appointment_time": ""}}

After completion, if the patient says anything else, reply with exactly:
{"status": "ended"}
"""


# ── Tool execution ─────────────────────────────────────────────────────────
def _execute_tool(name: str, inputs: dict) -> str:
    if name == "lookup_patient":
        record = find_patient(
            name=inputs.get("name"),
            dob=inputs.get("dob") or None,
            phone=inputs.get("phone") or None,
        )
        return json.dumps(record) if record else "NOT_FOUND"

    if name == "check_eligibility":
        result = _check_eligibility(
            insurance_id=inputs.get("insurance_id", ""),
            payer=inputs.get("payer", ""),
        )
        return json.dumps(result)

    if name == "fhir_get_slots":
        dept = inputs.get("department", "").lower()
        matched = [s for s in SLOTS if dept in s["specialty"].lower()]
        return json.dumps(matched if matched else SLOTS[:3])

    if name == "fhir_create_patient":
        fhir_id = create_patient(inputs)
        return json.dumps({"fhir_id": fhir_id, "status": "created"})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Main chat loop ─────────────────────────────────────────────────────────
async def chat(session_id: str, user_message: str) -> dict:
    history_key = f"session:{session_id}:history"
    collected_key = f"session:{session_id}:collected"

    history_json = redis_client.get(history_key)
    history = json.loads(history_json) if history_json else []

    if user_message == "__start__":
        history.append({"role": "user", "content": "begin"})
    else:
        history.append({"role": "user", "content": user_message})

    assistant_text = ""
    lookup_count = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )

        if response.stop_reason != "tool_use":
            assistant_text = "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            history.append({"role": "assistant", "content": assistant_text})
            break

        # Track lookup retries
        for block in response.content:
            if getattr(block, "name", "") == "lookup_patient":
                lookup_count += 1

        assistant_blocks = [_block_to_dict(b) for b in response.content]
        history.append({"role": "assistant", "content": assistant_blocks})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "lookup_patient" and lookup_count > MAX_LOOKUP_RETRIES:
                content = "MAX_RETRIES_EXCEEDED — tell the patient a staff member will assist them."
            else:
                content = _execute_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
            })

        history.append({"role": "user", "content": tool_results})

    redis_client.setex(history_key, 86400, json.dumps(history))

    result = {"reply": assistant_text, "status": "collecting", "data": None}

    if '{"status": "complete"' in assistant_text:
        try:
            json_str = assistant_text[assistant_text.find('{"status": "complete"'):]
            parsed = json.loads(json_str)
            if parsed.get("status") == "complete":
                result["status"] = "complete"
                result["data"] = parsed.get("data", {})
                for field in ["department", "copay", "appointment_doctor", "appointment_date", "appointment_time"]:
                    result["data"].setdefault(field, "")
                friendly = assistant_text[:assistant_text.find('{"status": "complete"')].strip()
                if not friendly:
                    d = result["data"]
                    friendly = (
                        f"Perfect! You're booked with {d.get('appointment_doctor', 'your doctor')}"
                        f" on {d.get('appointment_date', '')} at {d.get('appointment_time', '')}."
                        " You're all set — see you soon! ✓"
                    )
                result["reply"] = friendly
                redis_client.setex(collected_key, 86400, json.dumps(result["data"]))
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