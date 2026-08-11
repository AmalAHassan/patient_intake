"""
claude.py — Conversational intake loop, orchestrated across scoped agents.

Payment is no longer handled via Claude calling Stripe's MCP tools inside
the model loop. The payment agent just records the patient's choice
("now"/"later"); if "now", this file calls create_payment_link_via_mcp()
directly — a deterministic backend call to Stripe's real remote MCP
server, with zero AI involvement in that specific step.

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
from services.mcp_client import call_tool
from services.sms import send_appointment_confirmation
from services.stripe_mcp import create_payment_link_via_mcp
from services import orchestrator

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


def _strip_leaked_reasoning(text: str) -> str:
    """
    Fast pattern-based filter applied to EVERY agent turn. Two passes:
    1. Sentence-level narration removal — strips only the narrating
       sentences while keeping the rest of the message intact.
    2. Whole-message wipe — only for leaked content that never co-occurs
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
    "parent or legal guardian",
]


def _is_identity_agent_skipping_age_tool(text: str, age_tool_used_this_turn: bool) -> bool:
    """
    The minor check used to have the model do its own year-subtraction
    arithmetic and it was unreliable — wrong current year assumed, wrong
    handling of whether the birthday had passed yet, sometimes both in
    the same conversation. IDENTITY_PROMPT now requires calling
    `calculate_age` and trusting its `is_minor` field instead of doing
    any math itself. This is a deterministic backstop for the case where
    the model states an age-based determination (minor, guardian
    questions, restating an age) without having actually called that
    tool this turn — i.e. it's guessing again instead of using the tool.
    """
    if age_tool_used_this_turn:
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


def _is_identity_needlessly_reverifying_age(text: str, state: dict, user_message: str) -> bool:
    """
    Once age_checked is set in state, the identity agent should not ask
    the patient to confirm/reconfirm/verify their DOB again — with one
    exception: if the patient just said they're not a minor (in response
    to being asked for guardian info), the prompt explicitly allows
    asking them to re-enter their DOB and checking again. This backstop
    blocks every other re-ask of this shape.
    """
    if not state.get("age_checked"):
        return False
    lower = text.lower()
    if not any(m in lower for m in _AGE_REVERIFY_MARKERS):
        return False
    um_lower = (user_message or "").lower()
    if any(m in um_lower for m in _NOT_A_MINOR_MARKERS):
        return False
    return True


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


async def chat(session_id: str, user_message: str, client_ip: str = "unknown") -> dict:
    history_key    = f"session:{session_id}:history"
    collected_key  = f"session:{session_id}:collected"
    orch_state_key = f"session:{session_id}:orchestrator"

    history_json = redis_client.get(history_key)
    history      = json.loads(history_json) if history_json else []

    state_json = redis_client.get(orch_state_key)
    state      = json.loads(state_json) if state_json else orchestrator.default_state()

    history.append({"role": "user", "content": "begin" if user_message == "__start__" else user_message})

    assistant_text = ""
    reply_segments = []
    lookup_count   = 0
    slots_tool_used_this_turn = False
    age_tool_used_this_turn   = False

    for _ in range(MAX_TOOL_ITERATIONS):
        active_agent = orchestrator.get_active_agent(state)
        print(f"[orchestrator] iteration {_+1}/{MAX_TOOL_ITERATIONS} — active agent: {active_agent}")
        system       = orchestrator.build_system_prompt(active_agent)
        scoped_tools = orchestrator.get_tools_for_agent(active_agent, TOOLS)

        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=1024,
            temperature=TEMPERATURE,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=history,
            tools=scoped_tools,
        )

        if response.stop_reason != "tool_use":
            turn_text = " ".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            turn_text = _strip_leaked_reasoning(turn_text)
            turn_text = _force_list_item_newline(turn_text)
            turn_text = await _reflect(turn_text, history)
            print(f"[orchestrator] {active_agent} said: {turn_text[:200]!r}")

            handled_redirect = False
            parsed_redirect, turn_text_without_redirect = _extract_redirect(turn_text)
            if parsed_redirect is not None:
                target = parsed_redirect.get("redirect")
                if target == active_agent:
                    print(f"[orchestrator] REJECTED self-redirect: {active_agent} -> {active_agent}")
                    history.append({"role": "assistant", "content": turn_text_without_redirect})
                    history.append({
                        "role": "user",
                        "content": (
                            f"You just tried to redirect to '{target}', but you are "
                            f"ALREADY the {target} agent — targeting YOURSELF specifically "
                            f"is what was invalid, nothing else. This does NOT mean you "
                            f"should avoid redirecting in general — outputting a redirect "
                            f"JSON is still exactly the right mechanism, just never with "
                            f"yourself as the target. Continue exactly as your instructions "
                            f"describe: finish collecting whatever is still needed from the "
                            f"patient, and as soon as you are done, output the redirect to "
                            f"the correct NEXT (different) agent — do not hesitate to do "
                            f"this once you're actually finished."
                        ),
                    })
                    continue
                print(f"[orchestrator] {active_agent} -> {target} "
                      f"(reason: {parsed_redirect.get('reason')}, leftover_text: {turn_text_without_redirect[:80]!r})")
                state = orchestrator.apply_redirect(state, parsed_redirect)
                state["routing_turns_without_redirect"] = 0
                turn_text = turn_text_without_redirect
                handled_redirect = True

            if turn_text:
                is_fabricated_slots = (
                    active_agent == "scheduling"
                    and _is_scheduling_agent_fabricating(turn_text, state.get("slots_ever_called", False))
                )
                is_asking_before_tool = (
                    active_agent == "scheduling"
                    and not handled_redirect
                    and not state.get("slots_ever_called", False)
                    and _is_scheduling_agent_asking_before_tool(turn_text, state.get("slots_ever_called", False))
                )
                is_routing_straying = (
                    active_agent == "routing"
                    and not handled_redirect
                    and _is_routing_agent_straying_into_scheduling(turn_text)
                )
                is_guessing_age = (
                    active_agent == "identity"
                    and not handled_redirect
                    and _is_identity_agent_skipping_age_tool(turn_text, age_tool_used_this_turn)
                )
                is_needless_reverify = (
                    active_agent == "identity"
                    and not handled_redirect
                    and _is_identity_needlessly_reverifying_age(turn_text, state, user_message)
                )
                if is_fabricated_slots or is_asking_before_tool or is_routing_straying or is_guessing_age or is_needless_reverify:
                    if is_fabricated_slots:
                        reason = "fabricated slots without calling fhir_get_slots"
                    elif is_asking_before_tool:
                        reason = "asking day/time preference before calling fhir_get_slots"
                    elif is_routing_straying:
                        reason = "routing asking scheduling questions instead of handing off"
                    elif is_guessing_age:
                        reason = "stating a minor/age determination without calling calculate_age"
                    else:
                        reason = "needlessly re-verifying age after it was already checked"
                    print(f"[orchestrator] REJECTED ({reason}): {turn_text[:150]}")
                    history.append({"role": "assistant", "content": turn_text})
                    if is_fabricated_slots:
                        correction = (
                            "You mentioned specific doctors, dates, or times without "
                            "actually calling fhir_get_slots. Do not invent slot data. "
                            "Call fhir_get_slots now with the department, then present "
                            "ONLY the real results it returns."
                        )
                    elif is_asking_before_tool:
                        correction = (
                            "Call fhir_get_slots now, with just the department — do not "
                            "ask the patient for a day/time preference first. Show "
                            "whatever real slots it returns; THEN you can ask if they'd "
                            "like something different."
                        )
                    elif is_routing_straying:
                        correction = (
                            "You are the routing agent — you have no scheduling tools "
                            "and cannot show appointment times or availability. You "
                            "already have the department and reason. Do not ask about "
                            "day/time preference or offer to show available slots — "
                            "output ONLY the redirect JSON to hand off to scheduling "
                            "now: {\"redirect\": \"scheduling\", \"reason\": \"routing complete\"}"
                        )
                    elif is_guessing_age:
                        correction = (
                            "You just made a minor/age determination (mentioned being "
                            "under 18, years old, or guardian requirements) without "
                            "calling calculate_age this turn. Never compute age "
                            "yourself. Call calculate_age now with the patient's DOB "
                            "exactly as given, then base your response only on its "
                            "is_minor field."
                        )
                    else:
                        correction = (
                            "You already checked this patient's age earlier in this "
                            "conversation and they haven't said they're not a minor — "
                            "do not ask them to verify or reconfirm their date of "
                            "birth. Continue with whatever comes next in the normal "
                            "flow instead."
                        )
                    history.append({"role": "user", "content": correction})
                    continue
                reply_segments.append(turn_text)
                history.append({"role": "assistant", "content": turn_text})

            if handled_redirect:
                continue

            # Circuit breaker: routing has repeatedly failed to emit its
            # required redirect in several different ways. Rather than
            # chase every new variant, force forward progress
            # deterministically after 2 stalled turns.
            if active_agent == "routing":
                stall_count = state.get("routing_turns_without_redirect", 0) + 1
                state["routing_turns_without_redirect"] = stall_count
                if stall_count >= 2:
                    print(f"[orchestrator] FORCED ADVANCE: routing stalled {stall_count} "
                          f"turns without redirecting — advancing to scheduling regardless")
                    state["return_to"] = "routing"
                    state["current_agent"] = "scheduling"
                    state["routing_turns_without_redirect"] = 0

            assistant_text = " ".join(reply_segments).strip()
            break

        for block in response.content:
            block_type = getattr(block, "type", "")
            block_name = getattr(block, "name", "")
            if block_type == "tool_use" and block_name == "fhir_get_slots":
                print(f"[scheduling] fhir_get_slots called — input: {block.input}")
                slots_tool_used_this_turn = True
                state["slots_ever_called"] = True
            elif block_type == "tool_use" and block_name == "calculate_age":
                age_tool_used_this_turn = True
            elif block_type == "tool_use":
                print(f"[tool] {active_agent} called {block_name} — input: {block.input}")

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
            elif block.name == "calculate_age":
                content = _calculate_age(block.input.get("dob", ""))
                try:
                    parsed_age = json.loads(content)
                    if "error" not in parsed_age:
                        state["age_checked"] = True
                        state["is_minor"] = parsed_age.get("is_minor", False)
                except json.JSONDecodeError:
                    pass
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

    redis_client.setex(orch_state_key, 86400, json.dumps(state))
    redis_client.setex(history_key, 86400, json.dumps(history))

    if not assistant_text and reply_segments:
        assistant_text = " ".join(reply_segments).strip()

    if not assistant_text:
        assistant_text = (
            "Sorry, I'm having some trouble right now. A staff member will "
            "follow up with you shortly to continue your registration."
        )

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

                payment_choice = parsed.get("payment", "later")
                payment_url = None

                copay_str = data.get("copay", "0")
                try:
                    copay_cents = int(round(float(copay_str) * 100))
                except (ValueError, TypeError):
                    copay_cents = 0

                if payment_choice == "now" and copay_cents > 0:
                    description = (
                        f"{data.get('department', 'Visit')} copay - "
                        f"{data.get('appointment_doctor', '')} "
                        f"{data.get('appointment_date', '')}".strip()
                    )
                    link_result = await create_payment_link_via_mcp(copay_cents, description, session_id)
                    if "url" in link_result:
                        payment_url = link_result["url"]
                    else:
                        print(f"[stripe] Payment link creation failed, falling back to 'later': {link_result.get('error')}")
                        payment_choice = "later"

                result.update({
                    "reply":       friendly,
                    "status":      "complete",
                    "data":        data,
                    "payment":     payment_choice,
                    "payment_url": payment_url,
                })
                print(f"[intake] Payment decision: {payment_choice} — copay: {data.get('copay', '0')}")
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