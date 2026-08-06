"""
graph.py — LangGraph implementation of the intake orchestrator.

Replaces orchestrator.py's hand-rolled state dict + claude.py's manual
for-loop with a LangGraph StateGraph: five nodes (identity, insurance,
routing, scheduling, payment), each handling its OWN internal tool-calling
loop exactly as before.

IMPORTANT DESIGN NOTE: this does NOT use LangGraph's interrupt() for
"wait for the next patient message" — an earlier version did, but testing
revealed that interrupt() re-executes ALL prior code in a node from the
top on every resume (confirmed directly in LangGraph's own docs: "the
graph resumes from the start of the node, re-executing all logic"). For a
node making multiple real Anthropic API calls before reaching interrupt(),
that would silently re-bill every earlier call on every single patient
reply — a serious, quietly compounding cost bug.

Instead, each chat message is its own separate graph.ainvoke() call,
exactly like the current non-LangGraph system already works via Redis:
a node either hands off to another agent within the SAME invocation (a
redirect, signaled via just_redirected — safe, no re-execution risk
since it's a normal return, not an interrupt), or the invocation simply
ENDS once an agent has a plain question for the patient. The checkpointer
persists current_agent correctly, so the next real chat message becomes
a fresh, independent invocation that resumes at the right agent with no
re-execution of anything.

Deliberately keeps every guard function, prompt string, and the raw
Anthropic SDK call UNCHANGED, imported directly from claude.py and
orchestrator.py — this file only changes HOW turns are sequenced and
persisted, not what each agent is allowed to say or how misbehavior gets
caught. Cache_control is passed exactly as before, since we call the
Anthropic SDK directly rather than going through LangChain's model
wrapper — this avoids depending on langchain-anthropic's caching
middleware working correctly, per the migration-risk discussion.

Uses an in-memory checkpointer for now (MemorySaver) — sufficient for
unit tests and local dev. Swapping to AsyncPostgresSaver for production
persistence is a follow-up, one-line change once this core logic is
verified working.
"""
import json
from typing import TypedDict, Optional, Literal
from datetime import date

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from services import orchestrator
from services.mcp_client import call_tool
from services.stripe_mcp import create_payment_link_via_mcp
from services.claude import (
    anthropic_client,
    MODEL,
    TEMPERATURE,
    TOOLS,
    MAX_TOOL_ITERATIONS,
    MAX_LOOKUP_RETRIES,
    _strip_leaked_reasoning,
    _reflect,
    _extract_redirect,
    _is_scheduling_agent_fabricating,
    _is_scheduling_agent_asking_before_tool,
    _is_routing_agent_straying_into_scheduling,
    _block_to_dict,
)


class IntakeState(TypedDict):
    messages: list
    current_agent: str
    return_to: Optional[str]
    slots_ever_called: bool
    routing_turns_without_redirect: int
    last_routing_reply: str
    department: Optional[str]
    session_id: str
    lookup_count: int
    just_redirected: bool
    # Populated only once a terminal status is reached
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

VALID_DEPARTMENTS = [
    "Family Medicine", "OB/GYN", "Cardiology", "Urgent Care",
    "Mental Health", "Dermatology", "Pediatrics",
]


def _infer_department_from_messages(messages: list) -> Optional[str]:
    """
    Deterministic fallback for when department was never captured via a
    clean redirect JSON — e.g. the routing-repetition safety valve forces
    an advance to scheduling without ever emitting that JSON. Scans
    recent messages for an exact department name — same style as the
    other guard functions in this file: simple, deterministic, no model
    call involved.
    """
    for msg in reversed(messages[-6:]):
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        for dept in VALID_DEPARTMENTS:
            if dept.lower() in content.lower():
                return dept
    return None


def _make_agent_node(agent_name: str):
    """
    Returns a node function for one agent. All five nodes share this same
    implementation, parameterized by agent_name — mirrors how the old
    claude.py loop handled whichever agent was currently active, just
    scoped to a single agent per node instead of a generic mega-loop.
    """

    async def node(state: IntakeState) -> dict:
        messages = list(state["messages"])
        lookup_count = state.get("lookup_count", 0)
        slots_ever_called = state.get("slots_ever_called", False)
        routing_stall = state.get("routing_turns_without_redirect", 0)

        system = orchestrator.build_system_prompt(agent_name)
        scoped_tools = orchestrator.get_tools_for_agent(agent_name, TOOLS)

        for _ in range(MAX_TOOL_ITERATIONS):
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
                messages=messages,
                tools=scoped_tools,
            )

            if response.stop_reason != "tool_use":
                turn_text = " ".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                turn_text = _strip_leaked_reasoning(turn_text)
                turn_text = await _reflect(turn_text, messages)
                print(f"[graph] {agent_name} said: {turn_text[:200]!r}")

                handled_redirect = False
                next_agent = agent_name
                new_return_to = state.get("return_to")
                captured_department = state.get("department")

                parsed_redirect, turn_text_without_redirect = _extract_redirect(turn_text)
                if parsed_redirect is not None:
                    target = parsed_redirect.get("redirect")
                    if target == agent_name:
                        print(f"[graph] REJECTED self-redirect: {agent_name} -> {agent_name}")
                        messages.append({"role": "assistant", "content": turn_text_without_redirect})
                        messages.append({
                            "role": "user",
                            "content": SELF_REDIRECT_CORRECTION.format(target=target),
                        })
                        continue
                    if target in orchestrator.AGENTS:
                        print(f"[graph] {agent_name} -> {target} (reason: {parsed_redirect.get('reason')})")
                        new_return_to = agent_name
                        next_agent = target
                        routing_stall = 0
                        turn_text = turn_text_without_redirect
                        handled_redirect = True
                        if parsed_redirect.get("department"):
                            captured_department = parsed_redirect["department"]

                if turn_text:
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
                    if is_fabricated_slots or is_asking_before_tool or is_routing_straying:
                        if is_fabricated_slots:
                            correction = (
                                "You mentioned specific doctors, dates, or times without "
                                "actually calling fhir_get_slots. Do not invent slot data. "
                                "Call fhir_get_slots now with the department, then present "
                                "ONLY the real results it returns."
                            )
                        elif is_asking_before_tool:
                            correction = (
                                "Call fhir_get_slots now, with just the department — do "
                                "not ask the patient for a day/time preference first. Show "
                                "whatever real slots it returns; THEN you can ask if "
                                "they'd like something different."
                            )
                        else:
                            correction = (
                                "You are the routing agent — you have no scheduling "
                                "tools and cannot show appointment times or availability. "
                                "Do not ask about day/time preference — output ONLY the "
                                "redirect JSON to hand off to scheduling now: "
                                '{"redirect": "scheduling", "reason": "routing complete"}'
                            )
                        print(f"[graph] REJECTED (guard triggered): {turn_text[:150]}")
                        messages.append({"role": "assistant", "content": turn_text})
                        messages.append({"role": "user", "content": correction})
                        continue

                    messages.append({"role": "assistant", "content": turn_text})

                if handled_redirect:
                    # Same invocation continues immediately into the new
                    # agent's node — no waiting needed, no re-execution
                    # risk, since this never goes through interrupt().
                    return {
                        "messages": messages,
                        "current_agent": next_agent,
                        "return_to": new_return_to,
                        "routing_turns_without_redirect": 0,
                        "department": captured_department,
                        "slots_ever_called": slots_ever_called,
                        "lookup_count": lookup_count,
                        "just_redirected": True,
                    }

                if agent_name == "routing":
                    last_reply = state.get("last_routing_reply", "")
                    is_repeat = turn_text.strip().lower() == last_reply.strip().lower()
                    routing_stall = (routing_stall + 1) if is_repeat else 1

                    if routing_stall >= 2:
                        # Routing has said the EXACT same thing twice in a
                        # row — genuinely stuck, not just working through
                        # a legitimate multi-step conversation (department,
                        # then reason, then a referral check, etc. are all
                        # DIFFERENT text each time, so they never trigger
                        # this). Still show what it just said normally
                        # (don't discard a real reply), but append a clear
                        # transition and hand off cleanly on the NEXT
                        # invocation instead of cascading into scheduling
                        # mid-invocation with incomplete context.
                        #
                        # This safety-valve path bypasses the normal
                        # redirect-JSON department capture above (it never
                        # emits that JSON), so department falls back to a
                        # deterministic scan of recent messages instead of
                        # being silently left null going into scheduling.
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
                            "lookup_count": lookup_count,
                            "just_redirected": False,
                            "final_reply": transition_text,
                        }

                # Check for terminal statuses embedded in turn_text
                terminal = _check_terminal_status(turn_text, state["session_id"])
                if terminal is not None:
                    return {
                        "messages": messages,
                        "current_agent": agent_name,
                        "routing_turns_without_redirect": routing_stall,
                        "slots_ever_called": slots_ever_called,
                        "lookup_count": lookup_count,
                        "just_redirected": False,
                        **terminal,
                    }

                # Plain patient-facing question — this invocation ends
                # HERE, naturally. No interrupt(), no re-execution risk:
                # the NEXT patient message becomes an entirely separate
                # graph.ainvoke() call (same thread_id), which the
                # checkpointer resumes with current_agent already set
                # correctly to this same agent, ready to receive the
                # patient's reply as a fresh user message.
                return {
                    "messages": messages,
                    "current_agent": agent_name,
                    "routing_turns_without_redirect": routing_stall,
                    "last_routing_reply": turn_text if agent_name == "routing" else state.get("last_routing_reply", ""),
                    "department": captured_department,
                    "slots_ever_called": slots_ever_called,
                    "lookup_count": lookup_count,
                    "just_redirected": False,
                    "final_reply": turn_text,
                }

            # stop_reason == "tool_use" — execute tools, same as before
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
                elif block.name == "lookup_patient" and lookup_count > MAX_LOOKUP_RETRIES:
                    content = "MAX_RETRIES_EXCEEDED — tell the patient a staff member will assist them."
                else:
                    content = await call_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })
            messages.append({"role": "user", "content": tool_results})

        # MAX_TOOL_ITERATIONS exhausted without a plain reply — end this
        # invocation with a generic fallback rather than looping forever.
        fallback = (
            "Sorry, I'm having some trouble right now. A staff member "
            "will follow up with you shortly to continue your registration."
        )
        messages.append({"role": "assistant", "content": fallback})
        return {
            "messages": messages,
            "current_agent": agent_name,
            "slots_ever_called": slots_ever_called,
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
    Payment link creation (deterministic, session_id-linked) happens here,
    exactly as it did in claude.py's chat().
    """
    crisis_keywords = ["988", "suicide", "crisis lifeline", "911", "immediate danger", "emergency_redirect"]
    is_emergency = (
        '{"status": "emergency_redirect"}' in turn_text
        or any(kw in turn_text.lower() for kw in crisis_keywords)
    )
    if is_emergency:
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
            "payment_url": None,  # resolved separately, see resolve_payment()
        }

    return None


async def resolve_payment(state: IntakeState) -> dict:
    """
    Called by the API layer AFTER the graph reaches a "complete" status
    with payment == "now" — creates the real Stripe link deterministically,
    exactly as claude.py's chat() did inline. Kept as a separate function
    (not a graph node) since it's a one-shot side effect after completion,
    not part of the conversational flow itself.
    """
    if state.get("payment") != "now":
        return {}
    data = state.get("data") or {}
    copay_str = data.get("copay", "0")
    try:
        copay_cents = int(round(float(copay_str) * 100))
    except (ValueError, TypeError):
        copay_cents = 0
    if copay_cents <= 0:
        return {}
    description = (
        f"{data.get('department', 'Visit')} copay - "
        f"{data.get('appointment_doctor', '')} "
        f"{data.get('appointment_date', '')}".strip()
    )
    link_result = await create_payment_link_via_mcp(copay_cents, description, state["session_id"])
    if "url" in link_result:
        return {"payment_url": link_result["url"]}
    print(f"[graph] Payment link creation failed, falling back to 'later': {link_result.get('error')}")
    return {"payment": "later"}


def _route_after_agent(state: IntakeState) -> str:
    if state.get("status") in ("complete", "emergency_redirect", "staff_requested", "ended"):
        return END
    if state.get("just_redirected"):
        return state["current_agent"]
    return END


def build_graph(checkpointer=None):
    """
    Builds and compiles the intake StateGraph. Pass a checkpointer
    explicitly (e.g. AsyncPostgresSaver for production); defaults to an
    in-memory one, which is all unit tests and local dev need.
    """
    builder = StateGraph(IntakeState)
    for name in orchestrator.STEP_ORDER:
        builder.add_node(name, _make_agent_node(name))

    builder.set_conditional_entry_point(lambda state: state.get("current_agent", "identity"))
    for name in orchestrator.STEP_ORDER:
        builder.add_conditional_edges(name, _route_after_agent)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


# Module-level default graph instance for the API layer to import directly.
graph = build_graph()