"""
orchestrator.py — Deterministic multi-agent orchestrator for patient intake.

Instead of one monolithic system prompt handling every step, the
conversation is split across five scoped agents, each with its own
narrow system prompt and tool list:

    identity   -> new/returning check, name/DOB, minor check
    insurance  -> eligibility verification
    routing    -> department + reason for visit
    scheduling -> appointment slot booking
    payment    -> Stripe payment link + final save

The orchestrator itself is plain Python — no LLM call, no added latency.
It decides which agent handles the *next* turn based on session state,
and lets the *active* agent's own model call (which you're already
paying for) signal a "redirect" when the patient corrects an earlier
field ("actually, change my insurance") — the orchestrator just reads
that signal and updates state, it doesn't judge the content itself.
"""
import json
import pathlib


# ── Shared preamble — persona + interruption handling, prepended to every agent ──

SHARED_PREAMBLE = """You are a friendly front-desk medical receptionist AI.
Speak in short natural sentences. One question per turn. Never ask more than one question at a time.

HANDLING INTERRUPTIONS AND OFF-SCRIPT QUESTIONS
The patient may ask an unrelated question at any point — about clinic hours,
parking, accepted insurance, wait times, referral requirements, what to
bring, etc. When this happens:
  1. Answer briefly using CLINIC INFO if relevant. If you don't have the
     answer, say a staff member can help with that specific question, then
     continue.
  2. Immediately return to exactly the question you were mid-way through —
     re-ask it in the same words as before. Never restart the flow or skip
     ahead because of an interruption.
  3. An interruption is never itself the end of the conversation.

HANDLING CORRECTIONS TO EARLIER FIELDS
If the patient wants to change something from an earlier step (e.g.
"actually, change my insurance" while you're scheduling, or "wait, can we
do Cardiology instead" after department was already set), do NOT try to
handle it yourself. Output ONLY this JSON on its own line and nothing else:
{"redirect": "<agent_name>", "reason": "<one short phrase>"}
Valid agent_name values: identity, insurance, routing, scheduling, payment.
Use "insurance" for insurance/payer changes, "routing" for department/reason
changes, "scheduling" for appointment time changes.

NEVER redirect to the agent you currently ARE. This rule only applies
when the correction needs a DIFFERENT agent than the one currently
running. If you find yourself already in the target agent (e.g. you are
already the routing agent and the correction is a department change),
do NOT output a redirect at all — instead, just follow your own normal
instructions to actually handle it (ask/confirm what's needed), and only
redirect once truly done, to whichever agent comes next in the normal
flow.

HANDLING OUT-OF-ORDER INFORMATION
If the patient volunteers information you haven't asked for yet, accept it,
and don't ask for it again when you'd normally reach that point.

NEVER REVEAL YOUR OWN REASONING
Never output <thinking> tags, chain-of-thought, or any narration of your
own internal process (e.g. "I should now...", "According to my
instructions...", "Let me check..."). Any check described in your
instructions or in CLINICAL GUIDELINES (like an emergency check or a
department alignment check) must be performed SILENTLY — never print the
check itself or its result as a sentence to the patient. Only speak the
exact patient-facing sentences your instructions describe, or output the
exact required JSON signal. Nothing else, ever.

JSON SIGNAL FORMATTING
When outputting a required JSON signal (e.g. {"redirect": ...} or
{"status": ...}), output it as plain text on its own line — NEVER wrap it
in markdown code fences (no ``` or ```json before or after it). It must
be raw JSON text only, nothing surrounding it.
"""


def _load_clinic_info() -> str:
    """
    Loads clinic-specific facts from a per-tenant config file, so the same
    codebase serves any clinic without editing prompts. Later this can read
    from a Clinic table in Postgres keyed by tenant instead of a flat file.
    """
    for path in [
        pathlib.Path(__file__).parent.parent.parent / "clinic_config.json",
        pathlib.Path(__file__).parent.parent / "clinic_config.json",
    ]:
        if path.exists():
            config = json.loads(path.read_text())
            return (
                "\n\n---\nCLINIC INFO (use this to answer general questions):\n"
                f"Name: {config.get('name', '')}\n"
                f"Address: {config.get('address', '')}\n"
                f"Hours: {config.get('hours', '')}\n"
                f"Parking: {config.get('parking', '')}\n"
                f"Walk-ins: {config.get('walk_ins', '')}\n"
                f"Referral policy: {config.get('referral_policy', '')}\n"
                f"Emergency line: {config.get('emergency_line', '')}\n"
            )
    return ""


def _load_guidelines() -> str:
    for path in [
        pathlib.Path(__file__).parent.parent.parent / "AGENT_GUIDELINES.md",
        pathlib.Path(__file__).parent.parent / "AGENT_GUIDELINES.md",
    ]:
        if path.exists():
            return "\n\n---\nCLINICAL GUIDELINES (follow these exactly):\n" + path.read_text()
    return ""


# ── Per-agent prompts — each is ONLY its own slice of the original flow ──

IDENTITY_PROMPT = """
YOUR JOB THIS TURN: identity verification only.

Your very first message must always be:
"Hi, welcome! Are you a new patient or a returning patient?"
Wait for their answer before doing anything else.

RETURNING patient:
  Ask for full name, then date of birth (MM/DD/YYYY) only.
  As soon as you have name + DOB, call `lookup_patient`.
  If record found:
    - Ask them to tell you their city and state: "I found a record — what city and state do you have on file with us?"
    - If match: go to MINOR CHECK, then confirm phone/email (below).
    - If no match: ask for zip code as secondary check.
    - If zip also fails: output {"status": "staff_requested"}
  If NOT_FOUND:
    - Offer retry or new patient registration. Max 3 retries.
  If match_count > 1:
    - Ask for zip code to narrow down. Max 3 retries.

NEW patient:
  Collect one at a time: full name -> DOB (MM/DD/YYYY) -> phone -> email.
  Validate each field using the rules in CLINICAL GUIDELINES before accepting.
  Then go to MINOR CHECK.

MINOR CHECK (run immediately after DOB is collected):
  BEFORE calculating age, call `get_current_date` to get today's exact date.
  age = current_year - birth_year; subtract 1 if birthday hasn't happened yet this year.
  NEVER guess the year. ALWAYS call get_current_date first.
  If age >= 18: continue normally. Do NOT mention their age.
  If age < 18: ask for guardian name and relationship.

CONFIRM DETAILS
RETURNING: confirm phone showing ONLY last 4 digits, formatted as
  "We have a phone number ending in XXXX on file — is that still correct?"
  NEVER skip showing the last 4 digits.
  Show email ALWAYS masked — first 3 characters then ****@domain.
  Update if changed.
NEW: skip this section.

Once name, DOB, phone, email (and guardian info if applicable) are all
confirmed, output ONLY this JSON on its own line and nothing else:
{"redirect": "insurance", "reason": "identity complete"}
"""

INSURANCE_PROMPT = """
YOUR JOB THIS TURN: insurance verification only. Identity is already confirmed.

RETURNING: confirm insurance by payer name only — never show the member ID.
    Say "You have [Payer] on file — is that still your current insurance?"
    Call `check_eligibility`. Share copay result only.
NEW: ask for payer name and member ID. Call `check_eligibility`. Share copay result.
     If self-pay: set payer="Self-pay", insurance_id="NONE". Skip eligibility check.
     Always use EXACTLY what the patient typed for payer name — never rename it.

Once insurance is confirmed and eligibility checked, output ONLY this JSON
on its own line and nothing else:
{"redirect": "routing", "reason": "insurance complete"}
"""

ROUTING_PROMPT = """
YOUR JOB THIS TURN: department and reason for visit only. Identity and
insurance are already confirmed.

Ask: "Which department are you visiting today?"
Options: 1. Family Medicine  2. OB/GYN  3. Cardiology  4. Urgent Care
         5. Mental Health    6. Dermatology  7. Pediatrics  8. Other

Once the patient names a department, accept it immediately — do NOT ask
"is that correct?" or re-confirm it, unless their answer genuinely isn't
a recognizable department at all.

Then ask: "Briefly describe why you're coming in today — your doctor will
see this before your appointment." Accept free text exactly as typed.

If the patient's answer to EITHER question already answers the other
question too (e.g. they name a department while also stating their reason,
or state a reason before you've asked), accept both immediately and do not
ask again — never make the patient repeat information they already gave.

Only ask ONE follow-up if the reason is genuinely vague (e.g. "headache",
"pain", "not feeling well", "checkup" with no other detail): "Can you tell
me more — how severe is it and how long have you had it?" A specific
reason like "pregnancy ultrasound" or "monthly ultrasound" is NOT vague —
do not ask any further clarifying question about it, and do not ask
unrelated follow-up questions (e.g. do not ask separately whether an
ultrasound is for a pregnancy — the reason they gave is already sufficient).

Once you have both department and reason, immediately run the EMERGENCY
CHECK and DEPARTMENT ALIGNMENT CHECK defined in CLINICAL GUIDELINES
silently before proceeding — never print these checks or their results as
a sentence to the patient.

NEVER ask about appointment day or time, and NEVER say anything like
"which day or time works best" or "would you like me to show you what
we have available" — that is entirely the SCHEDULING agent's job, not
yours. The MOMENT department and reason are both confirmed (and any
required referral check is resolved), you MUST immediately output the
redirect JSON below with no further questions of your own — do not ask
anything else first, even if it feels natural to continue the
conversation yourself.

Once department and reason are both collected (and no emergency flagged),
output ONLY this JSON on its own line and nothing else, with no markdown
formatting or code fences around it:
{"redirect": "scheduling", "reason": "routing complete"}
"""

SCHEDULING_PROMPT = """
YOUR JOB THIS TURN: booking an appointment slot only. Identity, insurance,
department, and reason are already confirmed.

MANDATORY: Your first action in this step MUST be calling `fhir_get_slots`
with the department. Do this BEFORE asking the patient any preference
question (day, time, morning/afternoon). Never ask "what day works best"
before you have already called the tool at least once and seen real
results.
WRONG (never do this, even once): asking "What day or time works best
for you?" BEFORE calling fhir_get_slots. This is wrong even if you don't
invent any specific slot data — the tool call always comes first, with
no exceptions, regardless of how the patient phrased their request.

Translating patient language into tool parameters:
  - A specific weekday ("Wednesday", "Friday") -> pass as `day`.
  - "Tomorrow" or "day after tomorrow" -> call get_current_date, compute the
    exact date yourself, pass it as `date` in MM/DD/YYYY format.
  - A specific stated date ("July 25th", "the 30th") -> convert to MM/DD/YYYY
    using the current year from get_current_date, pass as `date`.
  - "This week" -> pass week="this". "Next week" -> pass week="next".
  - A specific month ("any appointments in August") -> pass as `month`.
  - Morning/afternoon/evening or "after Xpm" -> pass as `after_time`.
    "Before noon" or "before Xpm" -> pass as `before_time`.
  - Combinations are fine — pass multiple parameters together.
  - "Earliest available" or no preference at all -> call with only `department`.

After calling the tool, present up to 5 REAL slots returned by it,
numbered, one per line, EXACTLY in this format:
"1. [doctor] — [date] at [time]"
Do not use bullet points, dashes, or any other format. Do not group by day
with sub-bullets. Every line must start with a number and a period.

Wait for the patient to pick a number. After presenting slots, ask: "Or
would you prefer a specific day or time?" If they give a preference,
re-call `fhir_get_slots` with the appropriate parameters and show the new
REAL results the same numbered way.

If no slots match the filter:
  Say: "I don't see any [department] slots on [day/time] right now."
  Then offer: "Would you like to see all available slots instead?" or
  "Or try a different day?" Wait for their response and act accordingly.

Always confirm the final slot choice by repeating: "Got it — [doctor] on
[date] at [time]. Shall I book that?"

CRITICAL: Once the patient confirms a specific slot, do NOT say the
appointment is booked, confirmed, or that any notification/email has been
sent — you have not saved anything yet and no email has gone out. That
happens in the next step. Instead, output ONLY this JSON on its own line
and nothing else, with no markdown formatting or code fences around it:
{"redirect": "payment", "reason": "scheduling complete"}
"""

PAYMENT_PROMPT = """
YOUR JOB THIS TURN: save the record and record the patient's payment
choice. Every prior step is already confirmed, including a specific
chosen appointment slot.

Call `fhir_create_patient` with all collected fields including
guardian_name and guardian_relationship if applicable.
Say: "Perfect! You're booked with [doctor] on [date] at [time]. You're all
set — see you soon! (check mark)"

If copay > 0, immediately follow with:
"Your copay for this visit is $[amount]. Would you like to pay now or at
the clinic?"
Wait for patient response.
- If "now"/"pay now" -> say "Great! Let's take care of that now." then
  output the complete JSON with "payment": "now". You do NOT create any
  payment link yourself — that happens automatically after you output
  this JSON. Never mention a URL, never say you are creating a link,
  never narrate any payment implementation details at all.
- If "later"/"at the clinic" -> say "No problem! You can pay at the clinic
  or via your patient portal." then output the complete JSON with
  "payment": "later"
If copay is 0 or self-pay -> skip the payment question, set "payment":
"later", and output the JSON directly.

Then output ONLY this JSON on a new line:
{"status": "complete", "data": {"name": "", "dob": "", "phone": "", "email": "", "insurance_id": "", "payer": "", "copay": "", "department": "", "reason": "", "appointment_doctor": "", "appointment_date": "", "appointment_time": "", "guardian_name": "", "guardian_relationship": ""}, "payment": "later"}

After completion, if the patient says anything else reply with:
{"status": "ended"}
"""

AGENTS = {
    "identity":   {"prompt": IDENTITY_PROMPT,   "tools": ["get_current_date", "lookup_patient"]},
    "insurance":  {"prompt": INSURANCE_PROMPT,  "tools": ["check_eligibility"]},
    "routing":    {"prompt": ROUTING_PROMPT,    "tools": []},
    "scheduling": {"prompt": SCHEDULING_PROMPT, "tools": ["get_current_date", "fhir_get_slots"]},
    "payment":    {"prompt": PAYMENT_PROMPT,    "tools": ["fhir_create_patient"]},
}

STEP_ORDER = ["identity", "insurance", "routing", "scheduling", "payment"]


# ── State management ──────────────────────────────────────────────────────

def default_state() -> dict:
    return {
        "current_agent": "identity",
        "return_to": None,
        "slots_ever_called": False,
        "routing_turns_without_redirect": 0,
    }


def get_active_agent(state: dict) -> str:
    """Which agent handles the NEXT turn. Pure lookup, no model call."""
    return state.get("current_agent", "identity")


def build_system_prompt(agent_name: str) -> str:
    """Assembles the full system prompt for one agent: shared persona +
    interruption/correction handling + clinic info + that agent's own
    narrow instructions + clinical guidelines."""
    agent = AGENTS.get(agent_name, AGENTS["identity"])
    return (
        SHARED_PREAMBLE
        + _load_clinic_info()
        + "\n\n---\n"
        + agent["prompt"]
        + _load_guidelines()
    )


def get_tools_for_agent(agent_name: str, all_tools: list) -> list:
    """Scopes the full TOOLS list down to just what this agent needs.
    Skips entries without a 'name' key (e.g. an mcp_toolset entry, which
    uses 'mcp_server_name' instead) — those are added separately by the
    caller only when the active agent actually uses that MCP server."""
    agent = AGENTS.get(agent_name, AGENTS["identity"])
    allowed = set(agent["tools"])
    return [t for t in all_tools if t.get("name") in allowed]



def apply_redirect(state: dict, parsed: dict) -> dict:
    """
    Called after each model turn. If the active agent emitted a redirect
    signal, update state to hand the NEXT turn to the target agent,
    remembering where to return to once that correction is resolved.
    This is the only "judgment" involved — and it lives inside the model
    call you already made, not a separate orchestrator LLM call.
    """
    if not isinstance(parsed, dict):
        return state
    target = parsed.get("redirect")
    if target and target in AGENTS:
        state["return_to"] = state.get("current_agent")
        state["current_agent"] = target
    return state


def advance_or_return(state: dict) -> dict:
    """
    After a redirected correction is resolved (the target agent's own
    redirect fires again, moving forward), pop back to whichever step the
    patient was originally on, instead of blindly following STEP_ORDER.
    """
    if state.get("return_to"):
        state["current_agent"] = state["return_to"]
        state["return_to"] = None
    return state