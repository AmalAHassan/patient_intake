"""
claude.py — Conversational intake loop, orchestrated across scoped agents.
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
from services import orchestrator

CRISIS_NOTIFIER_URL = os.getenv("CRISIS_NOTIFIER_URL", "http://localhost:8001")

redis_client     = redis.from_url(settings.redis_url)
anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

MODEL               = "claude-haiku-4-5"
MAX_TOOL_ITERATIONS = 10
MAX_LOOKUP_RETRIES  = 3

STRIPE_MCP_KEY = os.getenv("STRIPE_MCP_RESTRICTED_KEY")

MCP_SERVERS = [
    {
        "type": "url",
        "url": "https://mcp.stripe.com",
        "name": "stripe",
        "authorization_token": STRIPE_MCP_KEY,
    },
]

# Full tool list — orchestrator.get_tools_for_agent() scopes this down to
# just what the currently active agent is allowed to call.
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

# Not part of TOOLS itself (it has no "name" key, so get_tools_for_agent
# would crash trying to filter it) — appended dynamically in chat() only
# when the active agent is flagged use_stripe_mcp in orchestrator.py.
#
# Wide open — every tool Stripe's remote MCP server exposes is available.
# Restricting this to a single named tool via "configs" was tried and
# reverted: it changed execution from server-side-automatic (mcp_tool_use)
# to client-handled (plain tool_use), which our code doesn't implement,
# causing silent failures. Wide-open means Claude may use the slower
# generic discovery chain (planner -> search -> details -> write, ~20s),
# but it's the configuration that reliably produces real, working links.
STRIPE_TOOLSET = {
    "type": "mcp_toolset",
    "mcp_server_name": "stripe",
    "default_config": {"enabled": True, "defer_loading": False},
}

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
       sentences ("let me use the planner...", "I need to resolve
       internally...") while keeping the rest of the message intact, since
       useful content (like a real payment link) can appear in the same
       reply right after the narration. A whole-message wipe would throw
       that away too.
    2. Whole-message wipe — only for leaked content that never co-occurs
       with anything useful (e.g. a full leaked emergency-check
       checklist), where dropping the entire message is safe.
    """
    if not text:
        return text

    # Strip explicit thinking tags and everything inside them
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # Strip stray markdown code fences the model sometimes wraps JSON
    # signals in, despite being told not to — this is a safety net on top
    # of the SHARED_PREAMBLE instruction forbidding it.
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text).strip()

    # Pass 1: remove individual narration sentences, keep the rest
    narration_markers = [
        "let me create", "let me use", "let me look up", "let me get",
        "i see there's a question", "resolve internally", "finalize the approach",
        "now i'll create", "i need to resolve", "internally about how",
        "let me check", "i need to check",
    ]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s for s in sentences if not any(m in s.lower() for m in narration_markers)]
    text = " ".join(sentences).strip()

    # Pass 2: whole-message wipe, only for leaks that never carry useful
    # content alongside them
    lower = text.lower()
    whole_wipe_markers = [
        "according to my instructions", "emergency check:", "department alignment check:",
        "no red flags", "no mismatch", "this is appropriate for",
    ]
    if any(m in lower for m in whole_wipe_markers):
        return ""

    return text


_FAKE_LINK_MARKERS = ["stripe.com/pay", "stripe.com/checkout", "stripe.com/payment"]
_REAL_STRIPE_LINK_RE = re.compile(r"https://(?:buy|checkout)\.stripe\.com/\S+")


def _contains_fabricated_stripe_link(text: str) -> bool:
    """
    Code-level safety net: the model has, more than once, written a
    plausible-looking but FAKE Stripe URL (e.g. 'stripe.com/pay') instead
    of actually invoking the Stripe MCP tool. Prompt instructions alone
    haven't fully stopped this. This catches it deterministically — if
    the text mentions stripe.com at all but doesn't contain a real
    buy.stripe.com/checkout.stripe.com link, treat it as fabricated.
    """
    if "stripe.com" not in text.lower():
        return False
    return _REAL_STRIPE_LINK_RE.search(text) is None


def _is_payment_agent_stalling(text: str, tool_used_this_turn: bool) -> bool:
    """
    Two recurring patterns despite prompt instructions:
    1. Asking an implementation-detail question (e.g. "would you like a
       click-once link or email delivery?") instead of just calling the
       Stripe tool with sensible defaults.
    2. Narrating an INTENTION to use Stripe ("I'll use the Stripe API to
       generate a payment link...") without ever actually calling a tool
       or including a real link — a declarative version of the same
       stall, which doesn't end in "?" so the question-based check alone
       wouldn't catch it, and doesn't mention "stripe.com" so the
       fabricated-link check wouldn't catch it either.
    Either way: if the tool wasn't actually invoked this turn, force it
    to proceed instead of talking around the action.
    """
    if tool_used_this_turn:
        return False
    lower = text.lower()
    if text.strip().endswith("?"):
        stall_markers = [
            "payment link", "payment option", "which payment", "sent to your email",
            "click once", "click-once", "patient portal or email", "would you prefer",
        ]
        if any(m in lower for m in stall_markers):
            return True
    narration_without_action_markers = [
        "i'll use the stripe", "i can help you with a payment link",
        "let me search for how", "don't have a direct payment link tool",
        "based on the stripe documentation",
    ]
    return any(m in lower for m in narration_without_action_markers)


def _payment_now_missing_link(text: str) -> bool:
    """
    Distinct failure from stalling/fabrication: the Stripe tool can
    genuinely SUCCEED (a real payment link is created server-side, visible
    in the tool result), but the model sometimes skips actually
    communicating that URL to the patient and jumps straight to the
    completion JSON. If the completion signals "payment": "now" (patient
    chose to pay online) but no real stripe.com link appears ANYWHERE in
    the text, the link was created but never delivered — that's still a
    failure from the patient's perspective (nothing to click), even
    though the tool technically worked.
    """
    if '"payment": "now"' not in text and "'payment': 'now'" not in text:
        return False
    return _REAL_STRIPE_LINK_RE.search(text) is None


_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*(am|pm)", re.IGNORECASE)
_SLOT_CONTEXT_RE = re.compile(
    r"(dr\.\s*\w+|\bdoctor\b|"
    r"mon|tue|wed|thu|fri|sat|sun|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    re.IGNORECASE,
)


def _is_scheduling_agent_fabricating(text: str, tool_used_this_turn: bool) -> bool:
    """
    Same class of problem as the Stripe stall/fabrication checks: despite
    explicit prompt instructions, the scheduling agent has repeatedly
    asked preference questions ("morning or afternoon?") or presented
    slot-shaped content (doctor names, specific dates/times) WITHOUT
    actually calling fhir_get_slots first — meaning it's hallucinating
    data rather than using the real tool. If both a clock time AND a
    doctor/weekday/month mention appear together, but the tool was never
    called this turn, treat it as fabricated. Deliberately lenient about
    exact phrasing/punctuation (commas after weekdays, doctor name before
    or after the time, etc.) rather than requiring one rigid format.
    """
    if tool_used_this_turn:
        return False
    if not _TIME_RE.search(text):
        return False
    return bool(_SLOT_CONTEXT_RE.search(text))


_ROUTING_STRAYING_MARKERS = [
    "which day or time", "day or time works", "show you what we have",
    "what we have available", "which day works", "available slot",
    "would you prefer a specific day", "morning or afternoon",
]


def _is_routing_agent_straying_into_scheduling(text: str) -> bool:
    """
    Recurring failure: after collecting department + reason (sometimes
    plus an ad-hoc referral check), the routing agent — which has ZERO
    tools — starts asking scheduling-flavored questions itself ("which
    day or time works best?") instead of immediately handing off to the
    scheduling agent. Since routing can't call fhir_get_slots at all,
    this always dead-ends once the patient actually answers. If routing
    asks a scheduling-shaped question without emitting a redirect, that's
    the bug — reject it and force the handoff instead.
    """
    lower = text.lower()
    return any(m in lower for m in _ROUTING_STRAYING_MARKERS)


_REDIRECT_JSON_RE = re.compile(r'\{\s*"redirect"\s*:.*?\}', re.DOTALL)


def _extract_redirect(text: str) -> tuple[dict | None, str]:
    """
    Finds and parses a {"redirect": ...} JSON signal anywhere in the text
    (not just at the very end — a naive slice-to-end-of-string approach
    broke once when the model wrapped the JSON in markdown code fences,
    since everything after the JSON, including the closing ```, got
    included in the slice and broke json.loads()).

    Returns (parsed_dict_or_None, remaining_text_with_redirect_removed).
    Also strips any leftover markdown fence remnants around where the
    JSON used to sit.
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
    stripe_tool_used_this_turn = False
    slots_tool_used_this_turn  = False

    for _ in range(MAX_TOOL_ITERATIONS):
        active_agent = orchestrator.get_active_agent(state)
        print(f"[orchestrator] iteration {_+1}/{MAX_TOOL_ITERATIONS} — active agent: {active_agent}")
        system       = orchestrator.build_system_prompt(active_agent)
        scoped_tools = orchestrator.get_tools_for_agent(active_agent, TOOLS)

        uses_stripe = orchestrator.agent_uses_stripe(active_agent)
        if uses_stripe:
            scoped_tools = scoped_tools + [STRIPE_TOOLSET]

        call_kwargs = dict(
            model=MODEL,
            max_tokens=1024,
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

        if uses_stripe:
            call_kwargs["mcp_servers"] = MCP_SERVERS
            call_kwargs["betas"] = ["mcp-client-2025-11-20"]
            response = anthropic_client.beta.messages.create(**call_kwargs)
        else:
            response = anthropic_client.messages.create(**call_kwargs)

        if response.stop_reason != "tool_use":
            turn_text = " ".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            turn_text = _strip_leaked_reasoning(turn_text)
            turn_text = await _reflect(turn_text, history)
            print(f"[orchestrator] {active_agent} said: {turn_text[:200]!r}")

            handled_redirect = False
            parsed_redirect, turn_text_without_redirect = _extract_redirect(turn_text)
            if parsed_redirect is not None:
                target = parsed_redirect.get("redirect")
                if target == active_agent:
                    # Self-redirect — this is never valid, and left
                    # unchecked it silently loops forever with no
                    # patient-facing text until MAX_TOOL_ITERATIONS is
                    # exhausted (exactly what happened in production).
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
                is_fake_link = _contains_fabricated_stripe_link(turn_text)
                is_stalling  = (
                    orchestrator.agent_uses_stripe(active_agent)
                    and _is_payment_agent_stalling(turn_text, stripe_tool_used_this_turn)
                )
                is_fabricated_slots = (
                    active_agent == "scheduling"
                    and _is_scheduling_agent_fabricating(turn_text, state.get("slots_ever_called", False))
                )
                is_routing_straying = (
                    active_agent == "routing"
                    and not handled_redirect
                    and _is_routing_agent_straying_into_scheduling(turn_text)
                )
                is_missing_link = (
                    active_agent == "payment"
                    and _payment_now_missing_link(turn_text)
                )
                if is_fake_link or is_stalling or is_fabricated_slots or is_routing_straying or is_missing_link:
                    if is_fake_link:
                        reason = "fabricated link"
                    elif is_stalling:
                        reason = "stalling question instead of acting"
                    elif is_fabricated_slots:
                        reason = "fabricated slots without calling fhir_get_slots"
                    elif is_routing_straying:
                        reason = "routing asking scheduling questions instead of handing off"
                    else:
                        reason = "completed without ever including the payment link"
                    print(f"[stripe] REJECTED ({reason}): {turn_text[:150]}")
                    history.append({"role": "assistant", "content": turn_text})
                    if is_fake_link:
                        correction = (
                            "That link is not valid — you did not actually call the "
                            "Stripe tool. Do not write out any stripe.com URL yourself. "
                            "Call the Stripe tool now and use ONLY the exact URL it "
                            "returns in its result."
                        )
                    elif is_stalling:
                        correction = (
                            "Do not ask the patient any implementation questions about "
                            "how the payment link is delivered. Use sensible defaults "
                            "(a standard one-time payment link) and call the Stripe "
                            "tool now — do not ask anything further."
                        )
                    elif is_fabricated_slots:
                        correction = (
                            "You mentioned specific doctors, dates, or times without "
                            "actually calling fhir_get_slots. Do not invent slot data. "
                            "Call fhir_get_slots now with the department, then present "
                            "ONLY the real results it returns."
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
                    else:
                        correction = (
                            "You already successfully created a real payment link — "
                            "look at the tool result from earlier in this conversation "
                            "and find the exact URL it returned. You jumped straight to "
                            "the completion JSON without ever telling the patient that "
                            "URL. Output ONE short message containing that exact link "
                            "and an instruction to click it, THEN output the completion "
                            "JSON — do not omit the link this time."
                        )
                    history.append({"role": "user", "content": correction})
                    continue
                reply_segments.append(turn_text)
                history.append({"role": "assistant", "content": turn_text})

            if handled_redirect:
                # Continue immediately with the newly active agent, same
                # turn — no extra message from the patient needed just to
                # move the conversation forward.
                continue

            # Circuit breaker: routing has repeatedly failed to emit its
            # required redirect in several different ways (silent
            # acknowledgment with no JSON, drifting into scheduling's job,
            # even going completely blank) — none of which match a single
            # detectable bad phrase. Rather than chase every new variant,
            # force forward progress deterministically: if routing
            # completes 2 turns in a row without actually redirecting,
            # advance the state ourselves regardless of what was said.
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
            if block_type == "mcp_tool_use":
                print(f"[stripe] MCP tool called: {block_name} — input: {block.input}")
                stripe_tool_used_this_turn = True
            elif block_type == "mcp_tool_result":
                print(f"[stripe] MCP tool result — is_error={block.is_error}: {str(block.content)[:200]}")
            elif block_type == "tool_use" and block_name == "fhir_get_slots":
                print(f"[scheduling] fhir_get_slots called — input: {block.input}")
                slots_tool_used_this_turn = True
                state["slots_ever_called"] = True
            elif block_type == "tool_use":
                # Catch-all for every OTHER tool call (fhir_create_patient,
                # lookup_patient, check_eligibility, etc.) so nothing is a
                # silent blind spot in the logs anymore.
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
        # Loop exhausted MAX_TOOL_ITERATIONS without ever landing on a
        # final plain reply (e.g. kept redirecting agent to agent), but
        # real patient-facing text was accumulated along the way — use it
        # instead of silently discarding it.
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
    if block.type == "mcp_tool_use":
        return {
            "type": "mcp_tool_use",
            "id": block.id,
            "name": block.name,
            "server_name": block.server_name,
            "input": block.input,
        }
    if block.type == "mcp_tool_result":
        # block.content isn't a plain string — it's a list of SDK objects
        # (e.g. BetaTextBlock) that json.dumps() can't serialize directly.
        # Extract just the text out of each item before storing.
        #
        # These can be VERY large — Stripe's discovery tools
        # (stripe_api_search, stripe_api_details) return chunks of raw
        # OpenAPI documentation, sometimes thousands of characters. The
        # model only needs the FULL text in the turn where it's actually
        # deciding what to do next; once that decision is made, this
        # content just sits in history getting resent (and billed as
        # input tokens) on every subsequent turn for the rest of the
        # conversation. Truncate what gets STORED — the model already
        # used the full version to make its immediate next move.
        MAX_STORED_TOOL_RESULT_CHARS = 500
        raw_content = block.content
        if isinstance(raw_content, list):
            serializable_content = [
                {
                    "type": "text",
                    "text": (
                        item.text[:MAX_STORED_TOOL_RESULT_CHARS] + "... [truncated for storage]"
                        if len(item.text) > MAX_STORED_TOOL_RESULT_CHARS else item.text
                    ),
                } if hasattr(item, "text") else str(item)[:MAX_STORED_TOOL_RESULT_CHARS]
                for item in raw_content
            ]
        else:
            text = str(raw_content)
            serializable_content = (
                text[:MAX_STORED_TOOL_RESULT_CHARS] + "... [truncated for storage]"
                if len(text) > MAX_STORED_TOOL_RESULT_CHARS else text
            )
        return {
            "type": "mcp_tool_result",
            "tool_use_id": block.tool_use_id,
            "is_error": block.is_error,
            "content": serializable_content,
        }
    return {"type": block.type}


async def get_session_data(session_id: str) -> dict:
    data_json = redis_client.get(f"session:{session_id}:collected")
    return json.loads(data_json) if data_json else {}