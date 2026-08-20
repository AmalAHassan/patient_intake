"""
graph.py — LangGraph implementation of the intake orchestrator.

Replaces orchestrator.py's hand-rolled state dict + claude.py's manual
for-loop with a LangGraph StateGraph: five nodes (identity, insurance,
routing, scheduling, payment), each handling its OWN internal tool-calling
loop exactly as before.

"""
import json
import re
from typing import TypedDict, Optional, Literal
from datetime import date

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from services import orchestrator
from services.mcp_client import call_tool
from services.claude import (
    anthropic_client,
    MODEL,
    TEMPERATURE,
    TOOLS,
    MAX_TOOL_ITERATIONS,
    MAX_LOOKUP_RETRIES,
    _strip_leaked_reasoning,
    _force_list_item_newline,
    _reflect,
    _extract_redirect,
    _is_scheduling_agent_fabricating,
    _is_scheduling_agent_asking_before_tool,
    _is_routing_agent_straying_into_scheduling,
    _is_identity_agent_skipping_age_tool,
    _is_identity_needlessly_reverifying_age,
    _is_new_patient_path,
    _is_masking_new_patient_data,
    _calculate_age,
    _block_to_dict,
)

# A single guard firing more than this many times in ONE turn means the
# model is genuinely stuck on this specific issue, not just needing one
# more nudge. Rather than burning through the entire MAX_TOOL_ITERATIONS
# budget, stop immediately and hand off to a real staff member instead.
MAX_GUARD_RETRIES_PER_TYPE = 3

# Numeric crisis codes need WORD-BOUNDARY matching, not plain substring —
# a plain "988" in kw in text.lower() check matches ANY digit sequence
# containing 988, including a patient's own birth year (07/22/1988) or
# phone number, causing a false mental-health-crisis alert on a
# completely ordinary identity confirmation. \b988\b only matches "988"
# as a standalone token — real text keywords like "suicide" don't have
# this collision risk, since they're not substrings of unrelated numbers,
# so only the numeric codes need this special handling.
_CRISIS_NUMERIC_CODES_RE = re.compile(r'\b(988|911)\b')
_CRISIS_TEXT_KEYWORDS = ["suicide", "crisis lifeline", "immediate danger", "emergency_redirect"]


class IntakeState(TypedDict):
    messages: list
    current_agent: str
    return_to: Optional[str]
    slots_ever_called: bool
    age_checked: bool
    routing_turns_without_redirect: int
    last_routing_reply: str
    department: Optional[str]
    session_id: str
    lookup_count: int
    just_redirected: bool
    status: Optional[str]
    final_reply: Optional[str]
    data: Optional[dict]
    payment: Optional[str]
    payment_url: Optional[str]


SELF_REDIRECT_CORRECTION = (
    "You just tried to redirect to '{target}', but you are ALREADY the "
    "{target} agent — targeting YOURSELF specifically is what was invalid, "
    "nothing else. This does NOT mean you should avoid redirecting in "
    "general — outputting a redirect JSON is still exactly the right "
    "mechanism, just never with yourself as the target. Continue exactly "
    "as your instructions describe: finish collecting whatever is still "
    "needed from the patient, and as soon as you are done, output the "
    "redirect to the correct NEXT (different) agent — do not hesitate to "
    "do this once you're actually finished."
)

AGE_GUESS_CORRECTION = (
    "You just asked about age, 18, or date-of-birth verification, or "
    "stated a minor/guardian determination — without calculate_age ever "
    "having been called yet in this conversation. Never ask the patient "
    "to confirm their age or DOB, and never guess or compute it "
    "yourself. Call calculate_age now with their DOB exactly as already "
    "given, then base your next message only on its is_minor field, "
    "silently."
)

AGE_REVERIFY_CORRECTION = (
    "You already checked this patient's age earlier in this conversation "
    "and they haven't said they're not a minor — do not ask them to "
    "verify or reconfirm their date of birth. Continue with whatever "
    "comes next in the normal flow instead."
)

MASKING_NEW_PATIENT_CORRECTION = (
    "This patient was NOT FOUND in the lookup — they typed their own "
    "phone and email THIS SAME conversation. You just masked one of them "
    "(\"ending in XXXX\" or \"abc****@domain\") — that format is WRONG "
    "here; it only applies to RETURNING patients confirming an existing "
    "record. Show phone and email in FULL, exactly as typed, and ask "
    "again."
)

NEXT_AGENT = {
    "identity":   "insurance",
    "insurance":  "routing",
    "routing":    "scheduling",
    "scheduling": "payment",
}

_CORRECTION_SIGNAL_WORDS = [
    "actually", "wait", "change", "instead", "correct that",
    "no i meant", "fix that", "go back", "that's wrong",
]

WRONG_TARGET_CORRECTION = (
    "You just redirected to '{target}', but the correct next step from "
    "{agent_name} is '{expected}' — not '{target}'. The patient's last "
    "message ('{last_message}') was not asking for any correction, so "
    "this must be your NORMAL completion redirect, which always targets "
    "'{expected}' from here, with no exceptions. Output the correct "
    'redirect now: {{"redirect": "{expected}", "reason": "..."}}'
)

VALID_DEPARTMENTS = [
    "Family Medicine", "OB/GYN", "Cardiology", "Urgent Care",
    "Mental Health", "Dermatology", "Pediatrics",
]


def _infer_department_from_messages(messages: list) -> Optional[str]:
    for msg in reversed(messages[-6:]):
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        for dept in VALID_DEPARTMENTS:
            if dept.lower() in content.lower():
                return dept
    return None


def _last_real_patient_message(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            return msg["content"]
    return ""


def _patient_requested_correction(last_message: str) -> bool:
    text = last_message.strip().lower()
    return any(word in text for word in _CORRECTION_SIGNAL_WORDS)


def _make_agent_node(agent_name: str):
    async def node(state: IntakeState) -> dict:
        messages = list(state["messages"])
        lookup_count = state.get("lookup_count", 0)
        slots_ever_called = state.get("slots_ever_called", False)
        age_checked = state.get("age_checked", False)
        routing_stall = state.get("routing_turns_without_redirect", 0)
        guard_fire_counts: dict = {}

        system = orchestrator.build_system_prompt(agent_name)
        scoped_tools = orchestrator.get_tools_for_agent(agent_name, TOOLS)

        for _ in range(MAX_TOOL_ITERATIONS):
            response = anthropic_client.messages.create(
                model=MODEL,
                max_tokens=1024,
                temperature=TEMPERATURE,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=scoped_tools,
            )

            if response.stop_reason != "tool_use":
                raw_text = " ".join(b.text for b in response.content if b.type == "text").strip()
                parsed_redirect, raw_text_without_redirect = _extract_redirect(raw_text)

                turn_text = _strip_leaked_reasoning(raw_text_without_redirect)
                turn_text = _force_list_item_newline(turn_text)
                turn_text = await _reflect(turn_text, messages)
                print(f"[graph] {agent_name} said: {turn_text[:200]!r}")

                handled_redirect = False
                next_agent = agent_name
                new_return_to = state.get("return_to")
                captured_department = state.get("department")

                turn_text_without_redirect = turn_text
                if parsed_redirect is not None:
                    target = parsed_redirect.get("redirect")
                    if target == agent_name:
                        print(f"[graph] REJECTED self-redirect: {agent_name} -> {agent_name}")
                        messages.append({"role": "assistant", "content": turn_text_without_redirect})
                        messages.append({"role": "user", "content": SELF_REDIRECT_CORRECTION.format(target=target)})
                        continue

                    if target in orchestrator.AGENTS:
                        expected_next = NEXT_AGENT.get(agent_name)
                        last_message = _last_real_patient_message(messages)

                        is_wrong_target = (
                            expected_next is not None
                            and target != expected_next
                            and not _patient_requested_correction(last_message)
                        )
                        if is_wrong_target:
                            print(f"[graph] REJECTED wrong-target redirect: {agent_name} -> {target} (expected {expected_next})")
                            messages.append({"role": "assistant", "content": turn_text_without_redirect})
                            messages.append({
                                "role": "user",
                                "content": WRONG_TARGET_CORRECTION.format(
                                    target=target, agent_name=agent_name,
                                    expected=expected_next, last_message=last_message,
                                ),
                            })
                            continue

                        print(f"[graph] {agent_name} -> {target} (reason: {parsed_redirect.get('reason')})")
                        new_return_to = agent_name
                        next_agent = target
                        routing_stall = 0
                        turn_text = turn_text_without_redirect
                        handled_redirect = True
                        if parsed_redirect.get("department"):
                            captured_department = parsed_redirect["department"]

                if turn_text:
                    last_message = _last_real_patient_message(messages)

                    is_fabricated_slots = (
                        agent_name == "scheduling"
                        and _is_scheduling_agent_fabricating(turn_text, slots_ever_called)
                    )
                    is_asking_before_tool = (
                        agent_name == "scheduling"
                        and not handled_redirect
                        and not slots_ever_called
                        and _is_scheduling_agent_asking_before_tool(turn_text, slots_ever_called)
                    )
                    is_routing_straying = (
                        agent_name == "routing"
                        and not handled_redirect
                        and _is_routing_agent_straying_into_scheduling(turn_text)
                    )
                    is_guessing_age = (
                        agent_name == "identity"
                        and not handled_redirect
                        and _is_identity_agent_skipping_age_tool(turn_text, age_checked)
                    )
                    is_needless_reverify = (
                        agent_name == "identity"
                        and not handled_redirect
                        and _is_identity_needlessly_reverifying_age(turn_text, age_checked, last_message)
                    )
                    is_masking_new_patient = (
                        agent_name == "identity"
                        and not handled_redirect
                        and _is_masking_new_patient_data(turn_text, _is_new_patient_path(messages))
                    )
                    if (is_fabricated_slots or is_asking_before_tool or is_routing_straying
                            or is_guessing_age or is_needless_reverify or is_masking_new_patient):
                        if is_fabricated_slots:
                            guard_name = "fabricated_slots"
                            correction = (
                                "You mentioned specific doctors, dates, or times without "
                                "actually calling fhir_get_slots. Do not invent slot data. "
                                "Call fhir_get_slots now with the department, then present "
                                "ONLY the real results it returns."
                            )
                        elif is_asking_before_tool:
                            guard_name = "asking_before_tool"
                            correction = (
                                "Call fhir_get_slots now, with just the department — do "
                                "not ask the patient for a day/time preference first. Show "
                                "whatever real slots it returns; THEN you can ask if "
                                "they'd like something different."
                            )
                        elif is_routing_straying:
                            guard_name = "routing_straying"
                            correction = (
                                "You are the routing agent — you have no scheduling "
                                "tools and cannot show appointment times or availability. "
                                "Do not ask about day/time preference — output ONLY the "
                                "redirect JSON to hand off to scheduling now: "
                                '{"redirect": "scheduling", "reason": "routing complete"}'
                            )
                        elif is_guessing_age:
                            guard_name = "guessing_age"
                            correction = AGE_GUESS_CORRECTION
                        elif is_needless_reverify:
                            guard_name = "needless_reverify"
                            correction = AGE_REVERIFY_CORRECTION
                        else:
                            guard_name = "masking_new_patient"
                            correction = MASKING_NEW_PATIENT_CORRECTION

                        guard_fire_counts[guard_name] = guard_fire_counts.get(guard_name, 0) + 1
                        print(f"[graph] REJECTED (guard={guard_name}, count={guard_fire_counts[guard_name]}): {turn_text[:150]}")

                        if guard_fire_counts[guard_name] > MAX_GUARD_RETRIES_PER_TYPE:
                            print(f"[graph] GUARD RETRY CEILING HIT for '{guard_name}' ({guard_fire_counts[guard_name]} attempts) — escalating to staff_requested")
                            escalation_msg = (
                                "I'm having trouble completing this step online right now. "
                                "A staff member will follow up with you shortly to finish "
                                "your registration."
                            )
                            messages.append({"role": "assistant", "content": escalation_msg})
                            return {
                                "messages": messages,
                                "current_agent": agent_name,
                                "routing_turns_without_redirect": routing_stall,
                                "slots_ever_called": slots_ever_called,
                                "age_checked": age_checked,
                                "lookup_count": lookup_count,
                                "just_redirected": False,
                                "status": "staff_requested",
                                "final_reply": escalation_msg,
                                "data": None,
                                "payment": None,
                                "payment_url": None,
                            }

                        messages.append({"role": "assistant", "content": turn_text})
                        messages.append({"role": "user", "content": correction})
                        continue

                    messages.append({"role": "assistant", "content": turn_text})

                if handled_redirect:
                    return {
                        "messages": messages,
                        "current_agent": next_agent,
                        "return_to": new_return_to,
                        "routing_turns_without_redirect": 0,
                        "department": captured_department,
                        "slots_ever_called": slots_ever_called,
                        "age_checked": age_checked,
                        "lookup_count": lookup_count,
                        "just_redirected": True,
                    }

                if agent_name == "routing":
                    last_reply = state.get("last_routing_reply", "")
                    is_repeat = turn_text.strip().lower() == last_reply.strip().lower()
                    routing_stall = (routing_stall + 1) if is_repeat else 1

                    if routing_stall >= 2:
                        print(f"[graph] FORCED ADVANCE: routing repeated itself {routing_stall}x")
                        transition_text = (
                            turn_text + " Let's go ahead and get you scheduled — "
                            "we can follow up on this afterward."
                        )
                        messages[-1] = {"role": "assistant", "content": transition_text}
                        return {
                            "messages": messages,
                            "current_agent": "scheduling",
                            "return_to": "routing",
                            "routing_turns_without_redirect": 0,
                            "last_routing_reply": "",
                            "department": captured_department or _infer_department_from_messages(messages),
                            "slots_ever_called": slots_ever_called,
                            "age_checked": age_checked,
                            "lookup_count": lookup_count,
                            "just_redirected": False,
                            "final_reply": transition_text,
                        }

                terminal = _check_terminal_status(turn_text, state["session_id"])
                if terminal is not None:
                    return {
                        "messages": messages,
                        "current_agent": agent_name,
                        "routing_turns_without_redirect": routing_stall,
                        "slots_ever_called": slots_ever_called,
                        "age_checked": age_checked,
                        "lookup_count": lookup_count,
                        "just_redirected": False,
                        **terminal,
                    }

                return {
                    "messages": messages,
                    "current_agent": agent_name,
                    "routing_turns_without_redirect": routing_stall,
                    "last_routing_reply": turn_text if agent_name == "routing" else state.get("last_routing_reply", ""),
                    "department": captured_department,
                    "slots_ever_called": slots_ever_called,
                    "age_checked": age_checked,
                    "lookup_count": lookup_count,
                    "just_redirected": False,
                    "final_reply": turn_text,
                }

            for block in response.content:
                block_type = getattr(block, "type", "")
                block_name = getattr(block, "name", "")
                if block_type == "tool_use" and block_name == "fhir_get_slots":
                    print(f"[graph] fhir_get_slots called — input: {block.input}")
                    slots_ever_called = True
                elif block_type == "tool_use":
                    print(f"[tool] {agent_name} called {block_name} — input: {block.input}")
                if getattr(block, "name", "") == "lookup_patient":
                    lookup_count += 1

            messages.append({"role": "assistant", "content": [_block_to_dict(b) for b in response.content]})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "get_current_date":
                    today = date.today()
                    content = json.dumps({
                        "today": today.isoformat(), "year": today.year,
                        "month": today.month, "day": today.day,
                    })
                elif block.name == "calculate_age":
                    content = _calculate_age(block.input.get("dob", ""))
                    try:
                        parsed_age = json.loads(content)
                        if "error" not in parsed_age:
                            age_checked = True
                    except json.JSONDecodeError:
                        pass
                elif block.name == "lookup_patient" and lookup_count > MAX_LOOKUP_RETRIES:
                    content = "MAX_RETRIES_EXCEEDED — tell the patient a staff member will assist them."
                else:
                    content = await call_tool(block.name, block.input)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
            messages.append({"role": "user", "content": tool_results})

        fallback = (
            "Sorry, I'm having some trouble right now. A staff member "
            "will follow up with you shortly to continue your registration."
        )
        messages.append({"role": "assistant", "content": fallback})
        return {
            "messages": messages,
            "current_agent": agent_name,
            "slots_ever_called": slots_ever_called,
            "age_checked": age_checked,
            "lookup_count": lookup_count,
            "just_redirected": False,
            "final_reply": fallback,
        }

    return node


def _check_terminal_status(turn_text: str, session_id: str) -> Optional[dict]:
    """
    Parses turn_text for the same terminal-status JSON signals the old
    chat() function checked for at the very end, after the loop exited.
    Returns a state-update dict if a terminal status was found, else None.

    Numeric crisis codes (988, 911) use WORD-BOUNDARY matching — a plain
    substring check would false-positive on any DOB, phone number, or
    address containing that digit sequence (e.g. a patient born in 1988).
    Text keywords ("suicide", etc.) don't have this collision risk, so
    they stay as plain substring checks.
    """
    is_emergency = (
        '{"status": "emergency_redirect"}' in turn_text
        or bool(_CRISIS_NUMERIC_CODES_RE.search(turn_text))
        or any(kw in turn_text.lower() for kw in _CRISIS_TEXT_KEYWORDS)
    )
    if is_emergency:
        matched_numeric = _CRISIS_NUMERIC_CODES_RE.findall(turn_text)
        matched_text = [kw for kw in _CRISIS_TEXT_KEYWORDS if kw in turn_text.lower()]
        print(f"[debug] EMERGENCY TRIGGERED — numeric: {matched_numeric}, text: {matched_text}")
        print(f"[debug] FULL untruncated turn_text: {turn_text!r}")
        friendly = turn_text
        if '{"status": "emergency_redirect"}' in turn_text:
            friendly = turn_text[:turn_text.find('{"status": "emergency_redirect"}')].strip()
        return {"status": "emergency_redirect", "final_reply": friendly, "data": None, "payment": None, "payment_url": None}

    if '{"status": "staff_requested"}' in turn_text:
        friendly = turn_text[:turn_text.find('{"status": "staff_requested"}')].strip()
        return {"status": "staff_requested", "final_reply": friendly, "data": None, "payment": None, "payment_url": None}

    if '{"status": "ended"}' in turn_text:
        return {"status": "ended", "final_reply": "", "data": None, "payment": None, "payment_url": None}

    if '{"status": "complete"' in turn_text:
        try:
            json_str = turn_text[turn_text.find('{"status": "complete"'):]
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if parsed.get("status") != "complete":
            return None

        data = parsed.get("data", {})
        for f in ["department", "copay", "appointment_doctor", "appointment_date",
                  "appointment_time", "guardian_name", "guardian_relationship"]:
            data.setdefault(f, "")

        friendly = turn_text[:turn_text.find('{"status": "complete"')].strip()
        if not friendly:
            friendly = (
                f"Perfect! You're booked with {data.get('appointment_doctor', 'your doctor')}"
                f" on {data.get('appointment_date', '')} at {data.get('appointment_time', '')}."
                " You're all set — see you soon! ✓"
            )

        return {
            "status": "complete",
            "final_reply": friendly,
            "data": data,
            "payment": parsed.get("payment", "later"),
            "payment_url": None,
        }

    return None


def _route_after_agent(state: IntakeState) -> str:
    if state.get("status") in ("complete", "emergency_redirect", "staff_requested", "ended"):
        return END
    if state.get("just_redirected"):
        return state["current_agent"]
    return END


def build_graph(checkpointer=None):
    builder = StateGraph(IntakeState)
    for name in orchestrator.STEP_ORDER:
        builder.add_node(name, _make_agent_node(name))

    builder.set_conditional_entry_point(lambda state: state.get("current_agent", "identity"))
    for name in orchestrator.STEP_ORDER:
        builder.add_conditional_edges(name, _route_after_agent)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


graph = build_graph()