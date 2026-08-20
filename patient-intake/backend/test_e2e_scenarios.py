"""
test_e2e_scenarios.py — Drives your ACTUAL running backend through several
full conversations end to end, printing every exchange so you can visually
scan for hallucinations, masking mistakes, stalls, or wrong redirects
across many scenarios in one run — instead of catching them one at a
time by hand in the browser.

This is NOT a unit test (no mocking) — it calls the real /intake/start
and /intake/message endpoints, which means it genuinely talks to Claude
and costs real API calls. Run it deliberately, not on every save.

ADAPTIVE TURNS: a fixed, linear script breaks the moment the bot asks
something NOT in the script — e.g. routing's optional "how severe is it
and how long have you had it?" follow-up for a vague symptom, or
identity's "...Sound good?" confirmation. Before sending the next REAL
scripted turn, this checks whether the bot's last reply looks like one
of a few KNOWN unscripted/short-confirmation questions; if so, it sends
a generic filler answer and logs it, WITHOUT consuming the next real
scripted line — so the actual script stays aligned once the bot moves
on. Scripted turns below deliberately do NOT include a redundant answer
to "...Sound good?" — that's now handled adaptively every time.

SETUP:
    1. Make sure your backend is running: uvicorn main:app --reload
    2. pip install httpx --break-system-packages
    3. Fill in EXISTING_PATIENT below with a REAL name + DOB + city/state
       from your own patients_enriched.csv — this script doesn't know
       your data, so the "returning patient" scenario will fail lookup
       or loop forever on the city/state confirmation without it.
       Find one with:
           head -5 backend/data/patients_enriched.csv
    4. python test_e2e_scenarios.py
"""
import httpx
import time
import sys

BASE_URL = "http://localhost:8000"

# ── Fill this in with a REAL row from your own CSV before running ──
# city_state must be EXACTLY what that patient's record actually has on
# file — the identity agent checks it as a match, not just any answer.
EXISTING_PATIENT = {
    "name": "Ashley Vasquez",
    "dob": "05/30/1971",
    "city_state": "Josephfort, Idaho",
}

# Automated red-flag patterns — cheap, mechanical checks. These catch the
# OBVIOUS failures (empty replies, dead ends, generic errors) so you don't
# have to read every line, but they are NOT a substitute for actually
# reading the transcripts below — subtler issues (wrong masking, a
# fabricated slot, an odd tone) won't trip these and need your own eyes.
RED_FLAG_PHRASES = [
    "something went wrong",
    "having some trouble right now",
    "1-800-lea-help",
]

# Known UNSCRIPTED or short-confirmation questions the bot might ask
# that aren't a distinct step in the fixed script — each maps to a
# generic filler answer. If the bot's reply matches one of these, we
# answer it and log it as an adaptive turn, WITHOUT consuming the next
# real scripted line. "sound good" specifically covers identity's
# "...I'll go ahead and register you... Sound good?" question, which is
# NOT listed as its own scripted turn below anymore.
UNSCRIPTED_PATTERNS = [
    (["how severe", "how long have you had"], "it's pretty mild, started about 2 days ago"),
    (["can you tell me more", "tell me more about"], "it's nothing too serious, just wanted it checked"),
    (["sound good"], "yes"),
]

MAX_ADAPTIVE_REPLIES_PER_TURN = 3  # safety cap — never loop forever on one spot


def _matches_any(text_lower: str, keywords: list[str]) -> bool:
    return any(k in text_lower for k in keywords)


def _post(path: str, json_body: dict) -> dict:
    resp = httpx.post(f"{BASE_URL}{path}", json=json_body, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def run_scenario(name: str, turns: list[str]) -> dict:
    """
    turns: the REAL scripted patient messages, in order. The bot may ask
    unscripted side-questions between them (see UNSCRIPTED_PATTERNS) —
    those get a generic reply without consuming a real scripted turn.
    """
    print(f"\n{'=' * 70}")
    print(f"SCENARIO: {name}")
    print(f"{'=' * 70}")

    transcript = []
    red_flags = []
    adaptive_turns_used = []
    empty_reply_streak = 0

    start = _post("/intake/start", {})
    session_id = start["session_id"]
    bot_msg = start.get("message", "")
    print(f"[bot] {bot_msg}")
    transcript.append(("bot", bot_msg))
    last_bot_reply = bot_msg

    turn_index = 0
    while turn_index < len(turns):
        # Check whether the bot's LAST reply looks like a known
        # unscripted/short-confirmation question before committing to
        # the next real scripted line. Loop briefly if it keeps asking
        # unscripted follow-ups, capped so a genuine bug can't hang the
        # script.
        adaptive_count = 0
        lower = last_bot_reply.lower()
        matched_filler = None
        for keywords, filler in UNSCRIPTED_PATTERNS:
            if _matches_any(lower, keywords):
                matched_filler = filler
                break

        while matched_filler is not None and adaptive_count < MAX_ADAPTIVE_REPLIES_PER_TURN:
            print(f"[you] (adaptive) {matched_filler}")
            transcript.append(("you-adaptive", matched_filler))
            adaptive_turns_used.append(f"Answered unscripted question with: {matched_filler!r}")

            result = _post("/intake/message", {"session_id": session_id, "message": matched_filler})
            reply = (result.get("reply") or "").strip()
            status = result.get("status", "collecting")
            print(f"[bot] {reply!r}  (status={status})")
            transcript.append(("bot", reply))
            last_bot_reply = reply
            adaptive_count += 1

            lower = reply.lower()
            matched_filler = None
            for keywords, filler in UNSCRIPTED_PATTERNS:
                if _matches_any(lower, keywords):
                    matched_filler = filler
                    break

        if adaptive_count >= MAX_ADAPTIVE_REPLIES_PER_TURN:
            red_flags.append("Bot kept asking unscripted questions past the adaptive-reply cap — likely a real stall")
            break

        # Now send the actual next scripted turn.
        turn = turns[turn_index]
        turn_index += 1
        print(f"[you] {turn}")
        transcript.append(("you", turn))

        try:
            result = _post("/intake/message", {"session_id": session_id, "message": turn})
        except Exception as e:
            red_flags.append(f"HTTP error after '{turn}': {e}")
            print(f"  !! HTTP ERROR: {e}")
            break

        reply = (result.get("reply") or "").strip()
        status = result.get("status", "collecting")
        print(f"[bot] {reply!r}  (status={status})")
        transcript.append(("bot", reply))
        last_bot_reply = reply

        if not reply:
            empty_reply_streak += 1
            red_flags.append(f"Empty reply after '{turn}' (status={status})")
        else:
            empty_reply_streak = 0

        if empty_reply_streak >= 2:
            red_flags.append("Two empty replies in a row — likely a dead end")
            break

        for phrase in RED_FLAG_PHRASES:
            if phrase in reply.lower():
                red_flags.append(f"Matched red-flag phrase {phrase!r} after '{turn}'")

        if status in ("staff_requested", "emergency_redirect", "ended"):
            red_flags.append(f"Terminated early with status={status} after '{turn}'")
            break
        if status == "complete":
            print(f"  -> Reached completion. data={result.get('data')}")
            break

        time.sleep(0.3)  # be gentle on rate limits between turns

    return {
        "name": name,
        "transcript": transcript,
        "red_flags": red_flags,
        "adaptive_turns_used": adaptive_turns_used,
    }


# ── Scenario definitions — only the REAL scripted turns; unscripted or
#    short-confirmation questions are handled adaptively above, not
#    listed here (no more redundant "yes" after "...Sound good?") ──────

SCENARIOS = [
    # (
    #     "New adult patient, self-pay, Family Medicine, through to slot picking",
    #     [
    #         "Jordan Ellis",
    #         "03/14/1990",
    #         "3125557890",
    #         "jordan.ellis@example.com",
    #         "42 Birchwood Ave, Naperville, IL, 60540",
    #         "yes",  # answers "Does all of that look correct?" — distinct wording, not adaptive-matched
    #         "self pay",
    #         "Family Medicine",
    #         "annual checkup",
    #         "1",
    #     ],
    # ),
    (
        "New adult patient, insurance, OB/GYN",
        [
            "Priya Nandan",
            "07/22/1988",
            "6305551234",
            "priya.n@example.com",
            "18 Rosewood Ct, Aurora, IL, 60506",
            "yes",
            "i have insurance",
            "Blue Cross",
            "MBR-7788-XYZQ",
            "OB/GYN",
            "monthly prenatal checkup",
            "1",
        ],
    ),
    (
        "New MINOR patient — should trigger guardian flow, never ask patient's own age directly",
        [
            "Casey Nguyen",
            "05/01/2012",
            "yes",
            "2245559988",
            "casey.parent@example.com",
            "9 Elm St, Joliet, IL, 60431",
            "Taylor Nguyen",
            "mother",
            "yes",  # answers "...are YOU the parent or legal guardian... right now?"
            "yes",  # answers the SEPARATE final "Is everything correct?" confirm-details question
            "self pay",
            "Pediatrics",
            "annual wellness visit",
            "1",
        ],
    ),
    (
        "Returning/existing patient — requires REAL name+DOB+city/state filled in above",
        [
            EXISTING_PATIENT["name"],
            EXISTING_PATIENT["dob"],
            EXISTING_PATIENT["city_state"],  # must exactly match the real record on file
            "yes",
            "yes",
            "Cardiology",
            "follow-up on blood pressure",
            "1",
        ],
    ),
    (
        "New patient, different department — Mental Health (deliberately vague reason)",
        [
            "Sam Whitfield",
            "11/09/1995",
            "8155553344",
            "sam.w@example.com",
            "77 Cedar Ln, Oswego, IL, 60543",
            "yes",
            "self pay",
            "Mental Health",
            "not feeling well lately",  # deliberately vague — SHOULD trigger the adaptive follow-up handler
            "1",
        ],
    ),
    # (
    #     "New patient, different department — Dermatology",
    #     [
    #         "Alex Turner",
    #         "02/28/1982",
    #         "7735556677",
    #         "alex.turner@example.com",
    #         "5 Maple Dr, Plainfield, IL, 60544",
    #         "yes",
    #         "self pay",
    #         "Dermatology",
    #         "a mole I want checked out",
    #         "1",
    #     ],
    # ),
]


def main():
    if EXISTING_PATIENT["name"].startswith("REPLACE_ME"):
        print(
            "!! EXISTING_PATIENT is still a placeholder — the returning-patient "
            "scenario will fail lookup or loop on the city/state question. Fill "
            "in a real name+DOB+city/state from your CSV before running, or "
            "ignore that one scenario's results.\n"
        )

    all_results = []
    for name, turns in SCENARIOS:
        result = run_scenario(name, turns)
        all_results.append(result)

    print(f"\n\n{'#' * 70}")
    print("SUMMARY")
    print(f"{'#' * 70}")
    total_flags = 0
    for r in all_results:
        flag_count = len(r["red_flags"])
        total_flags += flag_count
        status_icon = "❌" if flag_count else "✅"
        print(f"{status_icon} {r['name']} — {flag_count} red flag(s)")
        for f in r["red_flags"]:
            print(f"    - {f}")
        if r["adaptive_turns_used"]:
            print(f"    (adaptive replies used: {len(r['adaptive_turns_used'])})")
            for a in r["adaptive_turns_used"]:
                print(f"      · {a}")

    print(f"\nTotal red flags across all scenarios: {total_flags}")
    print(
        "\nRemember: these are only the MECHANICAL checks (empty replies, "
        "dead ends, generic errors). Scroll back up and actually read each "
        "transcript for masking mistakes, fabricated data, wrong tone, or "
        "anything that just feels off — that's where real hallucinations "
        "usually show up, and no automated check here catches those."
    )

    sys.exit(1 if total_flags else 0)


if __name__ == "__main__":
    main()