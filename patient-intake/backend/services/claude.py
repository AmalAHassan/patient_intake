"""
claude.py — Shared utilities for the intake agents (tool definitions,
deterministic guard functions, text-cleanup helpers). The actual
conversational loop lives in graph.py (LangGraph) — this file provides
the building blocks graph.py imports, but doesn't run a loop itself.

Payment is not handled via Claude calling Stripe's MCP tools inside the
model loop. The payment agent just records the patient's choice
("now"/"later"); the actual link creation happens in routes/intake.py's
/intake/create-payment-link endpoint, triggered by a real button click,
with zero AI involvement in that step.

temperature=0.2 is set on both model calls (main loop + reflection) —
these agents follow a structured script rather than doing creative
writing, so a low temperature makes them far more likely to follow the
same instruction the same way every time, instead of the default 1.0
producing "sometimes it asks a question first, sometimes it doesn't"
variance for the exact same situation.
"""
import json
import os
import re
import redis
import httpx
from datetime import date
from anthropic import Anthropic
from config import settings

CRISIS_NOTIFIER_URL = os.getenv("CRISIS_NOTIFIER_URL", "http://localhost:8001")

redis_client     = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

MODEL               = "claude-haiku-4-5"
MAX_TOOL_ITERATIONS = 10
MAX_LOOKUP_RETRIES  = 3
TEMPERATURE         = 0.2

# Full tool list — orchestrator.get_tools_for_agent() scopes this down to
# just what the currently active agent is allowed to call.
TOOLS = [
    {
        "name": "get_current_date",
        "description": "Get today's date and current year. Used for resolving relative date terms like 'tomorrow' or 'next week' when checking appointment slots.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "calculate_age",
        "description": "Calculate a patient's exact current age from their date of birth and whether they are a minor. ALWAYS call this instead of computing age yourself — never do the year-subtraction math in your own head, it is easy to get wrong. This is the only source of truth for age.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dob": {"type": "string", "description": "Date of birth in MM/DD/YYYY format, exactly as the patient provided it."},
            },
            "required": ["dob"],
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
        "description": "Get available appointment slots for a department. Optionally filter by weekday, time of day, week, exact date, or month. Use get_current_date first to resolve relative terms like 'tomorrow' or 'next week' into a concrete day/week/date value before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "department":  {"type": "string"},
                "day":         {"type": "string", "description": "A specific weekday name, e.g. 'monday', 'tuesday'. Use for requests like 'do you have anything Wednesday'."},
                "after_time":  {"type": "string", "description": "Earliest time preference, e.g. 'afternoon', 'after 2pm', 'morning'."},
                "before_time": {"type": "string", "description": "Latest time preference, e.g. 'before noon', 'before 3pm'."},
                "week":        {"type": "string", "description": "Either 'this' or 'next' — use for requests like 'this week' or 'next week'."},
                "date":        {"type": "string", "description": "An exact date in MM/DD/YYYY format — compute this yourself from get_current_date for relative terms like 'tomorrow' or a specific stated date like 'July 25th'."},
                "month":       {"type": "string", "description": "A month name, e.g. 'august' — use for requests like 'any appointments in August'."},
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
                "address":               {"type": "string"},
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

REFLECTION_PROMPT = """You are a silent quality checker for a medical intake AI.

Check the DRAFT RESPONSE against these rules:
1. PHONE: If confirming phone, must show last 4 digits as "ending in XXXX".
2. AGE: If asking for guardian, patient must actually be under 18.
3. EMAIL: Must be masked as abc****@domain.com — never show full email.
4. INSURANCE: Never show member ID.

IMPORTANT: Do NOT flag or modify responses that contain JSON status codes
like {"status": "complete"...}, {"status": "ended"}, or {"redirect": ...} —
these are system signals, not patient-facing text.

If the draft passes all rules, output ONLY the word: APPROVED
If something needs fixing, output ONLY the corrected message text with
no explanation, no preamble, no reasoning. Just the fixed message."""


def _is_risky_step(draft: str, history: list) -> bool:
    """Only reflect on messages that touch high-risk rules."""
    if '{"status":' in draft or '{"redirect"' in draft:
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
            temperature=TEMPERATURE,
            system=[
                {
                    "type": "text",
                    "text": REFLECTION_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{
                "role": "user",
                "content": f"HISTORY:\n{json.dumps(last_few, indent=2)}\n\nDRAFT:\n{draft}"
            }]
        )
        result = reflection_response.content[0].text.strip()
        result_lower = result.lower()

        leaked_markers = [
            "i need to", "checking the draft", "draft response",
            "the rules", "correctly avoids", "no phone number shown",
            "no email shown", "no guardian question",
        ]
        looks_leaked = (
            len(result) > len(draft) * 1.5
            or "approved" in result_lower
            or any(m in result_lower for m in leaked_markers)
        )
        if looks_leaked:
            return draft

        bad_prefixes = ["issue", "rule", "corrected:", "wait,", "let me", "the draft", "note:"]
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


_APOLOGY_OPENER_MARKERS = [
    "you're right", "you're absolutely right", "you are right",
    "i apologize", "my apologies", "sorry,", "sorry -",
]


def _strip_leaked_reasoning(text: str) -> str:
    """
    Fast pattern-based filter applied to EVERY agent turn, unconditionally
    — before _reflect() ever runs, and regardless of whether reflection
    fires at all. Three passes:
    1. Sentence-level narration removal — strips only the narrating
       sentences while keeping the rest of the message intact.
    2. Sentence-level apology-opener removal — the model occasionally
       opens a turn with "You're absolutely right — I apologize" as if
       responding to a correction that was never made (most often right
       after validating/summarizing a field). This is a main-agent
       generation quirk, not something reflection introduces or could
       catch after the fact — reflection only inspects the text IT
       produces when it actually rewrites something, so a stray apology
       already baked into the original draft would sail straight past
       it whenever reflection approves (or never fires at all).
    3. Whole-message wipe — only for leaked content that never co-occurs
       with anything useful (e.g. a full leaked emergency-check
       checklist), where dropping the entire message is safe.
    """
    if not text:
        return text

    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text).strip()

    narration_markers = [
        "let me create", "let me use", "let me look up", "let me get",
        "i see there's a question", "resolve internally", "finalize the approach",
        "now i'll create", "i need to resolve", "internally about how",
        "let me check", "i need to check",
    ]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s for s in sentences if not any(m in s.lower() for m in narration_markers)]
    text = " ".join(sentences).strip()

    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s for s in sentences if not any(m in s.lower() for m in _APOLOGY_OPENER_MARKERS)]
    text = " ".join(sentences).strip()

    lower = text.lower()
    whole_wipe_markers = [
        "according to my instructions", "emergency check:", "department alignment check:",
        "no red flags", "no mismatch", "this is appropriate for",
    ]
    if any(m in lower for m in whole_wipe_markers):
        return ""

    return text


_QUESTION_THEN_LIST_ITEM_RE = re.compile(r"(\?)[ \t]+(\d{1,2}\.\s)")


def _force_list_item_newline(text: str) -> str:
    """
    Deterministic layout fix, not a content fix. The routing and
    scheduling agents both present numbered lists (departments, slots),
    and the frontend renders each numbered line as a separate clickable
    option. Despite explicit prompt instructions and a WRONG example in
    both ROUTING_PROMPT and SCHEDULING_PROMPT, the model periodically
    glues the FIRST list item onto the same line as the question that
    precedes it (e.g. "Which department are you visiting today? 1.
    Family Medicine\\n2. OB/GYN..."). Items 2+ already have their own
    newline, so only item 1 silently loses its clickability — a real
    but easy-to-miss feature bug, since the text still reads fine to a
    human. This is purely a text-layout problem, not a judgment call, so
    it's more reliable to fix it mechanically than to re-loop the model
    and hope it reformats correctly this time.
    """
    return _QUESTION_THEN_LIST_ITEM_RE.sub(r"\1\n\2", text)


_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*(am|pm)", re.IGNORECASE)
_SLOT_CONTEXT_RE = re.compile(
    r"(dr\.\s*\w+|\bdoctor\b|"
    r"mon|tue|wed|thu|fri|sat|sun|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    re.IGNORECASE,
)


def _is_scheduling_agent_fabricating(text: str, tool_used_this_turn: bool) -> bool:
    """
    Despite explicit prompt instructions, the scheduling agent has
    repeatedly asked preference questions or presented slot-shaped
    content (doctor names, specific dates/times) WITHOUT actually calling
    fhir_get_slots first — meaning it's hallucinating data rather than
    using the real tool. If both a clock time AND a doctor/weekday/month
    mention appear together, but the tool was never called this turn,
    treat it as fabricated.
    """
    if tool_used_this_turn:
        return False
    if not _TIME_RE.search(text):
        return False
    return bool(_SLOT_CONTEXT_RE.search(text))


_SCHEDULING_PREFERENCE_STALL_MARKERS = [
    "what day works best", "what day or time works", "which day works",
    "what time works best", "when works best", "do you have a preference",
]


def _is_scheduling_agent_asking_before_tool(text: str, tool_used_this_turn: bool) -> bool:
    """
    Milder companion to _is_scheduling_agent_fabricating — that one only
    catches SPECIFIC invented slot data (a time + doctor name together).
    This catches the more common, milder failure: asking a day/time
    preference question BEFORE ever calling fhir_get_slots, even when no
    fabricated data is stated at all. SCHEDULING_PROMPT explicitly
    forbids this with a WRONG example, but it still slips through
    sometimes — this is a deterministic backstop for that exact pattern.
    """
    if tool_used_this_turn:
        return False
    lower = text.lower()
    return any(m in lower for m in _SCHEDULING_PREFERENCE_STALL_MARKERS)


_ROUTING_STRAYING_MARKERS = [
    "which day or time", "day or time works", "show you what we have",
    "what we have available", "which day works", "available slot",
    "would you prefer a specific day", "morning or afternoon",
]


def _is_routing_agent_straying_into_scheduling(text: str) -> bool:
    """
    Recurring failure: after collecting department + reason, the routing
    agent — which has ZERO tools — starts asking scheduling-flavored
    questions itself instead of immediately handing off to the
    scheduling agent.
    """
    lower = text.lower()
    return any(m in lower for m in _ROUTING_STRAYING_MARKERS)


_MINOR_DETERMINATION_MARKERS = [
    "under 18", "years old", "guardian's full name", "legal guardian",
    "parent or legal guardian", "18 or older", "are you 18",
    "your age", "how old are you", "confirm your date of birth",
    "verify your date of birth", "verify your age", "confirm you are",
]


def _is_identity_agent_skipping_age_tool(text: str, age_checked: bool) -> bool:
    """
    Deterministic backstop for the case where the model states an
    age-based determination (minor, guardian questions, restating an
    age) WITHOUT age ever having been genuinely calculated at any point
    in this conversation. Uses age_checked (persists across the WHOLE
    conversation, set once calculate_age genuinely succeeds) rather than
    a this-turn-only signal — a this-turn signal is structurally unable
    to distinguish "guessing at age right now, tool never called" from
    "tool was called an iteration or two ago, this is a legitimate
    guardian-name follow-up" — both look identical if you only look at
    whether the tool was called in the SAME turn as the text. Once
    age_checked is True, guardian-related follow-up questions are
    expected, correct behavior per IDENTITY_PROMPT ("never call
    calculate_age again") — not a violation — so this guard goes silent
    from that point forward for the rest of the conversation.
    """
    if age_checked:
        return False
    lower = text.lower()
    return any(m in lower for m in _MINOR_DETERMINATION_MARKERS)


_AGE_REVERIFY_MARKERS = [
    "verify your age", "confirm your date of birth is",
    "reconfirm your date of birth", "double check your age",
    "double-check your age", "make sure i have everything right",
]
_NOT_A_MINOR_MARKERS = [
    "not a minor", "i'm not", "im not", "i am not",
]


def _is_identity_needlessly_reverifying_age(text: str, age_checked: bool, user_message: str) -> bool:
    """
    Once age is checked, the identity agent should not ask the patient to
    confirm/reconfirm/verify their DOB again — with one exception: if the
    patient just said they're not a minor (in response to being asked for
    guardian info), the prompt explicitly allows asking them to re-enter
    their DOB and checking again. This backstop blocks every other re-ask
    of this shape.
    """
    if not age_checked:
        return False
    lower = text.lower()
    if not any(m in lower for m in _AGE_REVERIFY_MARKERS):
        return False
    um_lower = (user_message or "").lower()
    if any(m in um_lower for m in _NOT_A_MINOR_MARKERS):
        return False
    return True


_NEW_PATIENT_MARKER = "it looks like you're new to us"


def _is_new_patient_path(messages: list) -> bool:
    """
    Deterministic check for which CONFIRM DETAILS branch applies. Scans
    the full conversation for IDENTITY_PROMPT's exact not-found phrasing
    — if it's ever appeared, phone/email must be shown in FULL from here
    on, never masked. Returning patients never trigger this phrase at
    all, so its absence means the FOUND/masked branch applies instead.
    """
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and _NEW_PATIENT_MARKER in content.lower():
            return True
    return False


_MASKED_EMAIL_RE = re.compile(r"\w+\*{2,}@")


def _is_masking_new_patient_data(text: str, is_new_patient_path: bool) -> bool:
    """
    Despite IDENTITY_PROMPT's explicit instruction, the model
    occasionally masks phone/email for a NEW patient anyway — the exact
    format meant only for RETURNING patients confirming data they didn't
    just type themselves. A new patient typed every field this same
    conversation; there's nothing to hide from them. Same class of
    unreliability as the scheduling/routing guards elsewhere in this
    file — the prompt alone reduces but doesn't eliminate this, so it
    needs the same deterministic backstop.
    """
    if not is_new_patient_path:
        return False
    if _MASKED_EMAIL_RE.search(text):
        return True
    if "ending in" in text.lower():
        return True
    return False


_REDIRECT_JSON_RE = re.compile(r'\{\s*"redirect"\s*:.*?\}', re.DOTALL)


def _extract_redirect(text: str) -> tuple[dict | None, str]:
    """
    Finds and parses a {"redirect": ...} JSON signal anywhere in the text
    (not just at the very end — a naive slice-to-end-of-string approach
    broke once when the model wrapped the JSON in markdown code fences).

    Returns (parsed_dict_or_None, remaining_text_with_redirect_removed).
    """
    match = _REDIRECT_JSON_RE.search(text)
    if not match:
        return None, text
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, text
    remaining = (text[:match.start()] + text[match.end():]).strip()
    remaining = re.sub(r"```json", "", remaining, flags=re.IGNORECASE)
    remaining = re.sub(r"```", "", remaining).strip()
    return parsed, remaining


def _calculate_age(dob_str: str) -> str:
    """
    Deterministic replacement for the model doing age math itself. Given
    a DOB in MM/DD/YYYY (the format IDENTITY_PROMPT always asks for),
    returns the exact current age and whether the patient is a minor,
    computed with real Python date arithmetic instead of relying on the
    model to compute a correct current year and correctly handle whether
    the birthday has passed yet this year.

    Deliberately NOT routed through mcp_client.py — age math has nothing
    to do with external FHIR/insurance systems, so it's handled directly
    here instead of being (incorrectly) treated as an MCP tool call.
    """
    try:
        month, day, year = (int(p) for p in dob_str.strip().split("/"))
        birth = date(year, month, day)
        today = date.today()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        result = {"age": age, "is_minor": age < 18}
        print(f"[intake] calculate_age({dob_str}) -> {result}")
        return json.dumps(result)
    except Exception as e:
        print(f"[intake] calculate_age({dob_str!r}) failed: {e}")
        return json.dumps({
            "error": "Could not parse that date of birth. Ask the patient "
                     "to reconfirm it in MM/DD/YYYY format."
        })


def _block_to_dict(block) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": block.type}


async def get_session_data(session_id: str) -> dict:
    data_json = redis_client.get(f"session:{session_id}:collected")
    return json.loads(data_json) if data_json else {}