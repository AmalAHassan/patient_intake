"""
claude.py — Conversational intake loop.
"""
import json
import os
import pathlib
import redis
import httpx
from datetime import date
from anthropic import Anthropic
from config import settings
from services.mcp_client import call_tool
from services.sms import send_appointment_confirmation

CRISIS_NOTIFIER_URL = os.getenv("CRISIS_NOTIFIER_URL", "http://localhost:8001")

redis_client     = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

MODEL               = "claude-haiku-4-5"
MAX_TOOL_ITERATIONS = 10
MAX_LOOKUP_RETRIES  = 3

MCP_SERVERS = [
    {"type": "url", "url": os.getenv("MCP_PATIENT_LOOKUP_URL", "http://localhost:5001/sse"), "name": "patient-lookup"},
    {"type": "url", "url": os.getenv("MCP_ELIGIBILITY_URL",    "http://localhost:5002/sse"), "name": "eligibility"},
    {"type": "url", "url": os.getenv("MCP_EHR_URL",            "http://localhost:5003/sse"), "name": "ehr"},
]

TOOLS = [
    {
        "name": "get_current_date",
        "description": "Get today's date and current year. Call this immediately after collecting a patient's date of birth to accurately calculate their age.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
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
                "name":                  {"type": "string"},
                "dob":                   {"type": "string"},
                "phone":                 {"type": "string"},
                "email":                 {"type": "string"},
                "insurance_id":          {"type": "string"},
                "payer":                 {"type": "string"},
                "department":            {"type": "string"},
                "reason":                {"type": "string"},
                "appointment_doctor":    {"type": "string"},
                "appointment_date":      {"type": "string"},
                "appointment_time":      {"type": "string"},
                "guardian_name":         {"type": "string"},
                "guardian_relationship": {"type": "string"},
            },
            "required": ["name", "dob"],
        },
    },
]


def _load_guidelines() -> str:
    for path in [
        pathlib.Path(__file__).parent.parent.parent / "AGENT_GUIDELINES.md",
        pathlib.Path(__file__).parent.parent / "AGENT_GUIDELINES.md",
    ]:
        if path.exists():
            return "\n\n---\nCLINICAL GUIDELINES (follow these exactly):\n" + path.read_text()
    return ""


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
    - Ask them to tell you their city and state: "I found a record — what city and state do you have on file with us?"
    - If match: go to MINOR CHECK.
    - If no match: ask for zip code as secondary check.
    - If zip also fails: output {"status": "staff_requested"}
  If NOT_FOUND:
    - Offer retry or new patient registration. Max 3 retries.
  If match_count > 1:
    - Ask for zip code to narrow down. Max 3 retries.

NEW patient:
  Collect one at a time: full name → DOB (MM/DD/YYYY) → phone → email.
  Validate each field using the rules in CLINICAL GUIDELINES before accepting.
  Then go to MINOR CHECK.

MINOR CHECK (run immediately after DOB is collected, before asking for phone or email):
  BEFORE calculating age, call `get_current_date` to get today's exact date.
  Then calculate age precisely:
    - age = current_year - birth_year
    - if current month < birth month OR (current month == birth month AND current day < birth day): subtract 1
  Examples using today's real date:
    - Born 2000-08-10, today is 2026-07-13 → age 25 → NOT a minor
    - Born 2009-03-15, today is 2026-07-13 → age 17 → IS a minor
    - Born 2008-09-01, today is 2026-07-13 → age 17 → IS a minor
  NEVER guess the year. ALWAYS call get_current_date first.
  If age >= 18: continue normally. Do NOT mention their age.
  If age < 18: ask for guardian name and relationship.

STEP 3 — CONFIRM DETAILS
RETURNING: confirm phone showing ONLY last 4 digits.
  ALWAYS format it as: "We have a phone number ending in XXXX on file — is that still correct?"
  Replace XXXX with the actual last 4 digits of their phone number from the record.
  NEVER say "is this your correct number?" without the last 4 digits.
  NEVER skip showing the last 4 digits.
  Show email ALWAYS masked — first 3 characters then ****@domain. Example: chr****@example.com. Never show full email.
  Update if changed.
NEW: skip to STEP 4.

STEP 4 — INSURANCE
RETURNING: confirm insurance by payer name only — never show the member ID.
    Say "You have [Payer] on file — is that still your current insurance?"
    Call `check_eligibility`. Share copay result only.
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
If the reason is vague (e.g. "headache", "pain", "not feeling well"), ask one follow-up:
"Can you tell me more — how severe is it and how long have you had it?"
Use their answer to run the EMERGENCY CHECK before proceeding to scheduling.

STEP 7 — SCHEDULING
Call `fhir_get_slots` with the chosen department.
Present slots numbered, one per line. Wait for patient to pick a number.

STEP 8 — SAVE AND COMPLETE
Call `fhir_create_patient` with all collected fields including guardian_name and guardian_relationship if applicable.
Say: "Perfect! You're booked with [doctor] on [date] at [time]. You're all set — see you soon! ✓"

If copay > 0, immediately follow with:
"Your copay for this visit is $[amount]. Would you like to pay now or at the clinic?"
Wait for patient response.
- If they say "now" or "pay now" → say "Great! Let's take care of that now." then output the complete JSON with "payment": "now"
- If they say "later" or "at the clinic" → say "No problem! You can pay at the clinic or via your patient portal." then output the complete JSON with "payment": "later"
If copay is 0 or self-pay → skip the payment question, set "payment": "later", and output the JSON directly.

Then output ONLY this JSON on a new line:
{"status": "complete", "data": {"name": "", "dob": "", "phone": "", "email": "", "insurance_id": "", "payer": "", "copay": "", "department": "", "reason": "", "appointment_doctor": "", "appointment_date": "", "appointment_time": "", "guardian_name": "", "guardian_relationship": ""}, "payment": "later"}

After any completion or redirect, if the patient says anything else reply with:
{"status": "ended"}
"""

REFLECTION_PROMPT = """You are a silent quality checker for a medical intake AI.

Check the DRAFT RESPONSE against these rules:
1. PHONE: If confirming phone, must show last 4 digits as "ending in XXXX".
2. AGE: If asking for guardian, patient must actually be under 18.
3. EMAIL: Must be masked as abc****@domain.com — never show full email.
4. INSURANCE: Never show member ID.

IMPORTANT: Do NOT flag or modify responses that contain JSON status codes
like {"status": "complete"...} or {"status": "ended"} — these are system
signals, not patient-facing text.

If the draft passes all rules, output ONLY the word: APPROVED
If something needs fixing, output ONLY the corrected message text with
no explanation, no preamble, no reasoning. Just the fixed message."""


def _is_risky_step(draft: str, history: list) -> bool:
    """Only reflect on messages that touch high-risk rules."""
    # Never reflect on status JSON messages — they're handled by the backend
    if '{"status":' in draft:
        return False
    draft_lower = draft.lower()
    risky_keywords = [
        "phone", "number", "ending in",
        "minor", "guardian", "years old", "age",
        "member id", "insurance id",
        "@",
    ]
    return any(kw in draft_lower for kw in risky_keywords)


async def _reflect(draft: str, history: list) -> str:
    """Run reflection only on high-risk responses. Silent — never shows reasoning."""
    if not _is_risky_step(draft, history):
        return draft
    try:
        last_few = history[-4:] if len(history) >= 4 else history
        reflection_response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=REFLECTION_PROMPT,
            messages=[{
                "role": "user",
                "content": f"HISTORY:\n{json.dumps(last_few, indent=2)}\n\nDRAFT:\n{draft}"
            }]
        )
        result = reflection_response.content[0].text.strip()

        # If approved, return original
        if result.upper() == "APPROVED" or result.upper().startswith("APPROVED"):
            return draft

        # If meta-commentary leaked through, skip correction
        bad_prefixes = ["issue", "rule", "corrected:", "wait,", "let me", "the draft", "approved\n", "note:"]
        if any(result.lower().startswith(p) for p in bad_prefixes):
            print(f"[reflect] Bad output format — skipping: {result[:60]}")
            return draft

        print(f"[reflect] ✓ Corrected silently")
        return result

    except Exception as e:
        print(f"[reflect] Failed: {e}")
        return draft


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

    print(f"")
    print(f"[crisis] {'='*55}")
    print(f"[crisis] ⚠️  CRISIS ALERT DETECTED")
    print(f"[crisis] {'='*55}")
    print(f"[crisis] Type:      {alert_type}")
    print(f"[crisis] Patient:   {patient_name}")
    print(f"[crisis] Address:   {patient_address}")
    print(f"[crisis] IP:        {client_ip}")
    print(f"[crisis] Session:   {session_id}")
    print(f"[crisis] Reason:    {reason if isinstance(reason, str) else str(reason)}")
    print(f"[crisis] {'='*55}")
    print(f"")

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
            print(f"[crisis] Notifier server reached — alert forwarded")
    except Exception:
        print(f"[crisis] Notifier server not running — alert logged above")


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
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=system,
            tools=TOOLS,
            messages=history,
        )

        if response.stop_reason != "tool_use":
            assistant_text = "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            # Reflection pass — only runs on risky steps, silent to patient
            assistant_text = await _reflect(assistant_text, history)
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
            if block.name == "get_current_date":
                today = date.today()
                content = json.dumps({
                    "today": today.isoformat(),
                    "year":  today.year,
                    "month": today.month,
                    "day":   today.day,
                })
                print(f"[intake] get_current_date → {today.isoformat()}")
            elif block.name == "lookup_patient" and lookup_count > MAX_LOOKUP_RETRIES:
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

    crisis_keywords = ["988", "suicide", "crisis lifeline", "911", "immediate danger", "emergency_redirect"]
    is_emergency = '{"status": "emergency_redirect"}' in assistant_text or \
                   any(kw in assistant_text.lower() for kw in crisis_keywords)

    if is_emergency:
        friendly = assistant_text
        if '{"status": "emergency_redirect"}' in assistant_text:
            friendly = assistant_text[:assistant_text.find('{"status": "emergency_redirect"}')].strip()
        result.update({"reply": friendly, "status": "emergency_redirect"})
        text_lower = assistant_text.lower()
        is_crisis = any(kw in text_lower for kw in ["988", "suicidal", "self-harm", "tired of life", "can't do this"])
        await _send_crisis_alert(
            session_id=session_id,
            alert_type="mental_health_crisis" if is_crisis else "medical_emergency",
            reason=history[-2]["content"] if len(history) >= 2 else "unknown",
            client_ip=client_ip,
        )
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
                for f in ["department", "copay", "appointment_doctor", "appointment_date",
                          "appointment_time", "guardian_name", "guardian_relationship"]:
                    data.setdefault(f, "")
                friendly = assistant_text[:assistant_text.find('{"status": "complete"')].strip()
                if not friendly:
                    friendly = (
                        f"Perfect! You're booked with {data.get('appointment_doctor', 'your doctor')}"
                        f" on {data.get('appointment_date', '')} at {data.get('appointment_time', '')}."
                        " You're all set — see you soon! ✓"
                    )
                result.update({
                    "reply":   friendly,
                    "status":  "complete",
                    "data":    data,
                    "payment": parsed.get("payment", "later"),
                })
                print(f"[intake] Payment decision: {parsed.get('payment', 'later')} — copay: {data.get('copay', '0')}")
                redis_client.setex(collected_key, 86400, json.dumps(data))
                to_number = os.getenv("TWILIO_TO_NUMBER", data.get("phone", ""))
                send_appointment_confirmation(
                    to_number=to_number,
                    patient_name=data.get("name", ""),
                    doctor=data.get("appointment_doctor", ""),
                    date=data.get("appointment_date", ""),
                    time=data.get("appointment_time", ""),
                    department=data.get("department", ""),
                )
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