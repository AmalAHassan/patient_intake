import json
import redis
from anthropic import Anthropic
from config import settings
from services.patient_lookup import find_patient
 
redis_client = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
 
MODEL = "claude-haiku-4-5"
MAX_TOOL_ITERATIONS = 8
 
# Hardcoded slots for MVP — replace with FHIR Slot query later
AVAILABLE_SLOTS = [
    {"id": "s1", "doctor": "Dr. Patel", "date": "Mon Jun 9",  "time": "9:00 AM"},
    {"id": "s2", "doctor": "Dr. Patel", "date": "Mon Jun 9",  "time": "11:30 AM"},
    {"id": "s3", "doctor": "Dr. Patel", "date": "Tue Jun 10", "time": "1:00 PM"},
    {"id": "s4", "doctor": "Dr. Kim",   "date": "Tue Jun 10", "time": "8:30 AM"},
    {"id": "s5", "doctor": "Dr. Kim",   "date": "Wed Jun 11", "time": "10:00 AM"},
    {"id": "s6", "doctor": "Dr. Chen",  "date": "Thu Jun 12", "time": "9:30 AM"},
    {"id": "s7", "doctor": "Dr. Chen",  "date": "Fri Jun 13", "time": "8:00 AM"},
]
 
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
  - If tool returns match_count > 1: ask one clarifying question (e.g. confirm DOB or phone) before retrying.
 
NEW patient:
  - Collect in this order, one question at a time: full name, date of birth (MM/DD/YYYY), phone number, email address.
  - Then go to STEP 3.
 
STEP 3 — CONFIRM / COLLECT DETAILS
RETURNING patient:
  - Show what you have on file and ask if it's still correct, e.g.:
    "I have your phone as {phone} and email as {email} — are those still correct?"
  - If yes: move on. If something changed: ask what changed and update it.
 
NEW patient:
  - You already collected these in STEP 2 — skip straight to STEP 4.
 
STEP 4 — INSURANCE
RETURNING patient:
  - Say "I see you have {insurance_provider} on file — is that still active?"
  - If yes: keep the existing payer and member_id from the record.
  - If no or changed: ask for new payer name, then new member ID.
 
NEW patient:
  - Ask "What insurance do you have?" then ask for their member ID.
  - If they say no insurance or self-pay: set payer to "Self-pay" and insurance_id to "NONE".
 
STEP 5 — DEPARTMENT
Ask: "Which department are you visiting today?"
Then list these options on separate lines:
  1. Family Medicine
  2. OB/GYN
  3. Cardiology
  4. Urgent Care
  5. Mental Health
  6. Dermatology
  7. Pediatrics
  8. Other
Accept a number or the department name. If they say Other, ask them to describe which department.
Store the answer as the department field.
 
STEP 6 — REASON FOR VISIT
Ask: "Briefly describe why you're coming in today — your doctor will see this before your appointment."
Accept their free-text answer exactly as typed. Do not rephrase or summarize it.
 
STEP 7 — CONFIRM AND COMPLETE
Read back a summary:
  "Just to confirm — [name], [department], reason: [their exact words]. Is that all correct?"
If they confirm: output the completion JSON immediately.
If they want to change something: fix it and re-confirm.
 
COMPLETION:
Say exactly:
"Perfect! I've got you booked with [doctor] on [date] at [time]. You're all set — see you soon!"

After completion, if the patient says anything else, reply with exactly:
status ended
"""
 
TOOLS = [
    {
        "name": "lookup_patient",
        "description": (
            "Look up a patient in the practice database. Call as soon as you have the patient's "
            "name plus EITHER their date of birth OR their phone number. Returns the matching "
            "patient record (with insurance, phone, email, member_id) or null if not found."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full name as provided by the caller."},
                "dob":  {"type": "string", "description": "Date of birth in MM/DD/YYYY format."},
                "phone":{"type": "string", "description": "Phone number in any format."},
            },
            "required": ["name"],
        },
    }
]
 
 
async def chat(session_id: str, user_message: str) -> dict:
    history_key   = f"session:{session_id}:history"
    collected_key = f"session:{session_id}:collected"
    stage_key     = f"session:{session_id}:stage"
 
    history_json = redis_client.get(history_key)
    history = json.loads(history_json) if history_json else []
 
    current_stage = redis_client.get(stage_key)
    current_stage = current_stage.decode() if current_stage else "intake"
 
    # ── SCHEDULING STAGE ──────────────────────────────────────────
    # Patient has already confirmed intake and is now picking a slot
    if current_stage == "scheduling":
        return _handle_slot_pick(session_id, user_message, history_key, collected_key, stage_key, history)
 
    # ── INTAKE STAGE ──────────────────────────────────────────────
    if user_message == "__start__":
        history.append({"role": "user", "content": "begin"})
    else:
        history.append({"role": "user", "content": user_message})
 
    assistant_text = ""
 
    for _ in range(MAX_TOOL_ITERATIONS):
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )
 
        if response.stop_reason == "tool_use":
            assistant_blocks = [_block_to_dict(b) for b in response.content]
            history.append({"role": "assistant", "content": assistant_blocks})
 
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "lookup_patient":
                    record = find_patient(
                        name=block.input.get("name"),
                        dob=block.input.get("dob"),
                        phone=block.input.get("phone"),
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(record) if record else "NOT_FOUND",
                    })
 
            history.append({"role": "user", "content": tool_results})
            continue
 
        assistant_text = "".join(
            b.text for b in response.content if b.type == "text"
        ).strip()
        history.append({"role": "assistant", "content": assistant_text})
        break
 
    redis_client.setex(history_key, 86400, json.dumps(history))
 
    # ── Check for completion JSON ──────────────────────────────────
    if '{"status": "complete"' in assistant_text:
        try:
            json_str = assistant_text[assistant_text.find('{"status": "complete"'):]
            parsed = json.loads(json_str)
            if parsed.get("status") == "complete":
                data = parsed.get("data", {})
                data.setdefault("department", "")
                redis_client.setex(collected_key, 86400, json.dumps(data))
 
                # Advance to scheduling stage
                redis_client.setex(stage_key, 86400, "scheduling")
 
                # Build slot picker message
                slot_msg = _build_slot_message(data.get("department", "your department"))
 
                return {
                    "reply": slot_msg,
                    "status": "scheduling",
                    "data": data,
                    "slots": AVAILABLE_SLOTS,
                }
        except json.JSONDecodeError:
            pass
 
    return {"reply": assistant_text, "status": "collecting", "data": None}
 
 
def _build_slot_message(department: str) -> str:
    lines = [f"Great! Let's get you booked for {department}. Here are the available appointments — just reply with the number of the slot you'd like:\n"]
    for i, slot in enumerate(AVAILABLE_SLOTS, 1):
        lines.append(f"  {i}. {slot['doctor']} — {slot['date']} at {slot['time']}")
    return "\n".join(lines)
 
 
def _handle_slot_pick(session_id, user_message, history_key, collected_key, stage_key, history):
    """Handle the patient picking an appointment slot."""
    collected_json = redis_client.get(collected_key)
    data = json.loads(collected_json) if collected_json else {}
 
    # Try to parse slot number from message
    choice = user_message.strip()
    slot = None
 
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(AVAILABLE_SLOTS):
            slot = AVAILABLE_SLOTS[idx]
 
    if not slot:
        # Couldn't parse — ask again
        msg = f"Sorry, just reply with a number between 1 and {len(AVAILABLE_SLOTS)} to pick your slot."
        return {"reply": msg, "status": "scheduling", "data": data, "slots": AVAILABLE_SLOTS}
 
    # Slot chosen — store it and complete
    data["appointment"] = {
        "doctor": slot["doctor"],
        "date": slot["date"],
        "time": slot["time"],
    }
    redis_client.setex(collected_key, 86400, json.dumps(data))
    redis_client.setex(stage_key, 86400, "done")
 
    confirmation = (
        f"You're all set! ✓\n\n"
        f"Your appointment is confirmed with {slot['doctor']} on {slot['date']} at {slot['time']}.\n"
        f"We'll see you then, {data.get('name', '').split()[0]}!"
    )
 
    return {
        "reply": confirmation,
        "status": "complete",
        "data": data,
    }
 
 
def _block_to_dict(block) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return {"type": block.type}
 
 
async def get_session_data(session_id: str) -> dict:
    data_json = redis_client.get(f"session:{session_id}:collected")
    return json.loads(data_json) if data_json else {}
 