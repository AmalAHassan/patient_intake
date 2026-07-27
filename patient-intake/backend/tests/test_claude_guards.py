"""
tests/test_claude_guards.py — Unit tests for the deterministic safety-net
functions in claude.py (fake-link detection, stalling detection, slot
fabrication detection, reasoning-leak stripping, redirect parsing).

These are pure string/regex logic — no Anthropic API call, no MCP call,
no Redis. Safe to run on every save or in CI with zero cost.

NOTE: importing services.claude triggers module-level Settings loading
(requires a valid .env with ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL
etc. — see config.py) and creates redis/Anthropic client objects, but
does NOT make any network calls at import time. Run these from your
normal backend/ virtualenv where .env is already set up. If you want
these tests to have zero external dependencies at all (recommended long
term), move the guard functions into their own services/guards.py module
with no imports from config/redis/anthropic.

Run with:
    pip install pytest --break-system-packages
    pytest backend/tests/test_claude_guards.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.claude import (
    _contains_fabricated_stripe_link,
    _is_payment_agent_stalling,
    _is_scheduling_agent_fabricating,
    _strip_leaked_reasoning,
    _is_risky_step,
    _extract_redirect,
    _payment_now_missing_link,
)


# ── Fake Stripe link detection ──────────────────────────────────────────

def test_real_buy_stripe_link_is_not_flagged():
    text = "Here's your link: https://buy.stripe.com/test_14AeV6b2ka53b0yggsawo00"
    assert _contains_fabricated_stripe_link(text) is False


def test_real_checkout_stripe_link_is_not_flagged():
    text = "Click here: https://checkout.stripe.com/pay/cs_live_abc123"
    assert _contains_fabricated_stripe_link(text) is False


def test_fabricated_stripe_com_pay_link_is_flagged():
    """Regression test — this exact fake URL was shown to a real patient."""
    text = "Here's your payment link: https://stripe.com/pay"
    assert _contains_fabricated_stripe_link(text) is True


def test_fabricated_stripe_com_checkout_link_is_flagged():
    """Regression test — a second fake variant seen in production."""
    text = "[Click here to pay](https://stripe.com/checkout)"
    assert _contains_fabricated_stripe_link(text) is True


def test_no_stripe_mention_at_all_is_not_flagged():
    text = "Your appointment is confirmed for Tuesday at 2pm."
    assert _contains_fabricated_stripe_link(text) is False


# ── Payment agent stalling detection ────────────────────────────────────

def test_stalling_question_without_tool_use_is_flagged():
    """Regression test — the exact phrasing that leaked to a patient."""
    text = (
        "For this copay of $20, which payment option works best for you — "
        "would you prefer a simple payment link you can click once, or "
        "would you like it sent to your email?"
    )
    assert _is_payment_agent_stalling(text, tool_used_this_turn=False) is True


def test_stalling_not_flagged_if_tool_was_actually_used():
    text = "Which payment option works best for you?"
    assert _is_payment_agent_stalling(text, tool_used_this_turn=True) is False


def test_non_question_statement_is_not_flagged_as_stalling():
    text = "Your copay is $25. Here's your payment link."
    assert _is_payment_agent_stalling(text, tool_used_this_turn=False) is False


def test_narration_without_link_or_tool_use_is_flagged_as_stalling():
    """Regression test — this exact declarative (non-question) narration
    was shown to a real patient, claiming to handle payment without ever
    calling a tool or including any real link. Doesn't end in '?' and
    never mentions 'stripe.com', so neither the question-based stall
    check nor the fake-link check alone would have caught it."""
    text = (
        "Great! I don't have a direct payment link tool available. Let "
        "me search for how to create a simple payment link for this "
        "copay. Based on the Stripe documentation, I can help you with "
        "a payment link. I'll use the Stripe API to generate a payment "
        "link for the $25 copay. Great! Let's take care of that now."
    )
    assert _is_payment_agent_stalling(text, tool_used_this_turn=False) is True


def test_payment_now_missing_link_is_flagged():
    """Regression test — the Stripe tool genuinely succeeded (a real
    link was created server-side) but the model jumped straight to the
    completion JSON without ever telling the patient the URL. Nothing
    to click, even though the tool call itself worked."""
    text = '{"status": "complete", "data": {"copay": "25"}, "payment": "now"}'
    assert _payment_now_missing_link(text) is True


def test_payment_now_with_real_link_is_not_flagged():
    text = (
        "Here's your payment link: https://buy.stripe.com/test_abc123 "
        '{"status": "complete", "data": {"copay": "25"}, "payment": "now"}'
    )
    assert _payment_now_missing_link(text) is False


def test_payment_later_without_link_is_not_flagged():
    """A copay deferred to the clinic never needs a link at all."""
    text = '{"status": "complete", "data": {"copay": "25"}, "payment": "later"}'
    assert _payment_now_missing_link(text) is False


def test_unrelated_question_is_not_flagged_as_stalling():
    text = "What city and state do you have on file with us?"
    assert _is_payment_agent_stalling(text, tool_used_this_turn=False) is False


# ── Scheduling agent fabrication detection ──────────────────────────────

def test_fabricated_slot_with_doctor_and_time_is_flagged():
    text = "How about Tuesday, July 30th at 9:00 AM with Dr. Patel?"
    assert _is_scheduling_agent_fabricating(text, tool_used_this_turn=False) is True


def test_fabricated_slot_list_with_dashes_is_flagged():
    """Regression test — the exact bullet-list format a patient saw,
    with no fhir_get_slots call behind it."""
    text = (
        "Here are a few morning options:\n"
        "- Tuesday, July 30th at 9:00 AM\n"
        "- Wednesday, July 31st at 9:30 AM\n"
        "Which works best for you?"
    )
    assert _is_scheduling_agent_fabricating(text, tool_used_this_turn=False) is True


def test_real_slots_not_flagged_when_tool_was_used():
    text = "1. Dr. Patel — Tue Jul 30 at 9:00 AM\n2. Dr. Chen — Wed Jul 31 at 1:00 PM"
    assert _is_scheduling_agent_fabricating(text, tool_used_this_turn=True) is False


def test_preference_question_without_slot_content_is_not_flagged():
    """This wouldn't have caught the "morning or afternoon?" stall on its
    own — that's a prompt problem, not a fabrication problem — but a
    plain question with no doctor/date/time shouldn't trip this check."""
    text = "Would morning or afternoon work better for you?"
    assert _is_scheduling_agent_fabricating(text, tool_used_this_turn=False) is False


# ── Reasoning leak stripping ─────────────────────────────────────────────

def test_thinking_tags_are_removed():
    text = "<thinking>I should check the rules here</thinking>Your appointment is confirmed."
    result = _strip_leaked_reasoning(text)
    assert "<thinking>" not in result
    assert "Your appointment is confirmed." in result


def test_narration_sentence_removed_but_real_link_survives():
    """Regression test — narration used to wipe the ENTIRE message,
    including the real payment link that came right after it."""
    text = (
        "Let me use the planner to finalize the approach. "
        "Here's your payment link: https://buy.stripe.com/test_abc123"
    )
    result = _strip_leaked_reasoning(text)
    assert "let me use the planner" not in result.lower()
    assert "https://buy.stripe.com/test_abc123" in result


def test_markdown_json_fences_are_stripped():
    text = '```json {"status": "ended"} ```'
    result = _strip_leaked_reasoning(text)
    assert "```" not in result


def test_full_checklist_leak_is_wiped_entirely():
    text = "1. EMERGENCY CHECK: no red flags. 2. DEPARTMENT ALIGNMENT CHECK: this is appropriate for family medicine."
    assert _strip_leaked_reasoning(text) == ""


def test_clean_patient_facing_text_passes_through_unchanged():
    text = "Which department are you visiting today?"
    assert _strip_leaked_reasoning(text) == text


# ── Redirect extraction (regression coverage for the markdown-fence bug) ─

def test_extract_redirect_plain_json():
    text = '{"redirect": "scheduling", "reason": "routing complete"}'
    parsed, remaining = _extract_redirect(text)
    assert parsed == {"redirect": "scheduling", "reason": "routing complete"}
    assert remaining == ""


def test_extract_redirect_with_leading_patient_facing_text():
    text = 'Got it, thanks! {"redirect": "payment", "reason": "scheduling complete"}'
    parsed, remaining = _extract_redirect(text)
    assert parsed["redirect"] == "payment"
    assert remaining == "Got it, thanks!"


def test_extract_redirect_wrapped_in_markdown_fences():
    """Regression test — this EXACT input leaked raw JSON + fences
    directly to a patient before this fix. Slicing to end-of-string
    instead of using a bounded regex broke json.loads() here."""
    text = '```json {"redirect": "scheduling", "reason": "appointment time change"} ```'
    parsed, remaining = _extract_redirect(text)
    assert parsed is not None
    assert parsed["redirect"] == "scheduling"
    assert "```" not in remaining
    assert '{"redirect"' not in remaining


def test_extract_redirect_returns_none_when_absent():
    text = "Which department are you visiting today?"
    parsed, remaining = _extract_redirect(text)
    assert parsed is None
    assert remaining == text


# ── Reflection risk detection ────────────────────────────────────────────

def test_status_json_is_never_flagged_as_risky():
    text = '{"status": "complete", "data": {}}'
    assert _is_risky_step(text, history=[]) is False


def test_redirect_json_is_never_flagged_as_risky():
    text = '{"redirect": "insurance", "reason": "test"}'
    assert _is_risky_step(text, history=[]) is False


def test_phone_confirmation_is_flagged_as_risky():
    text = "We have a phone number ending in 1234 on file — is that still correct?"
    assert _is_risky_step(text, history=[]) is True


def test_plain_department_question_is_not_risky():
    text = "Which department are you visiting today?"
    assert _is_risky_step(text, history=[]) is False