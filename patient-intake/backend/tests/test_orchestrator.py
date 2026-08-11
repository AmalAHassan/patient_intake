"""
tests/test_orchestrator.py — Unit tests for the deterministic orchestrator.

No API calls, no network, no cost. Everything here is pure Python logic,
so this can run on every save / in CI with zero external dependencies.

Run with:
    pip install pytest --break-system-packages
    pytest backend/tests/test_orchestrator.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import orchestrator


def test_default_state():
    state = orchestrator.default_state()
    assert state["current_agent"] == "identity"
    assert state["return_to"] is None


def test_get_active_agent_returns_current():
    state = {"current_agent": "scheduling", "return_to": None}
    assert orchestrator.get_active_agent(state) == "scheduling"


def test_get_active_agent_falls_back_to_identity_if_missing():
    assert orchestrator.get_active_agent({}) == "identity"


def test_apply_redirect_updates_state_and_remembers_return_to():
    state = {"current_agent": "scheduling", "return_to": None}
    parsed = {"redirect": "insurance", "reason": "insurance change"}
    new_state = orchestrator.apply_redirect(state, parsed)
    assert new_state["current_agent"] == "insurance"
    assert new_state["return_to"] == "scheduling"


def test_apply_redirect_ignores_invalid_agent_name():
    state = {"current_agent": "scheduling", "return_to": None}
    parsed = {"redirect": "not_a_real_agent"}
    new_state = orchestrator.apply_redirect(state, parsed)
    # Should be unchanged — "not_a_real_agent" isn't in AGENTS
    assert new_state["current_agent"] == "scheduling"


def test_apply_redirect_ignores_non_dict_input():
    state = {"current_agent": "identity", "return_to": None}
    result = orchestrator.apply_redirect(state, "not a dict")
    assert result == state


def test_advance_or_return_pops_back_to_saved_step():
    state = {"current_agent": "insurance", "return_to": "scheduling"}
    new_state = orchestrator.advance_or_return(state)
    assert new_state["current_agent"] == "scheduling"
    assert new_state["return_to"] is None


def test_advance_or_return_noop_when_nothing_to_return_to():
    state = {"current_agent": "identity", "return_to": None}
    new_state = orchestrator.advance_or_return(state)
    assert new_state["current_agent"] == "identity"


def test_get_tools_for_agent_scopes_correctly():
    all_tools = [
        {"name": "calculate_age"},
        {"name": "get_current_date"},
        {"name": "lookup_patient"},
        {"name": "check_eligibility"},
        {"name": "fhir_get_slots"},
        {"name": "fhir_create_patient"},
    ]
    # identity now uses calculate_age (deterministic age/is_minor lookup)
    # instead of get_current_date + model-side arithmetic — see
    # IDENTITY_PROMPT's MINOR CHECK section for why that changed.
    identity_tools = orchestrator.get_tools_for_agent("identity", all_tools)
    names = {t["name"] for t in identity_tools}
    assert names == {"calculate_age", "lookup_patient"}

    # scheduling is unaffected by that change — still needs
    # get_current_date for translating "tomorrow"/"next week" etc. into
    # concrete dates before calling fhir_get_slots.
    scheduling_tools = orchestrator.get_tools_for_agent("scheduling", all_tools)
    names = {t["name"] for t in scheduling_tools}
    assert names == {"get_current_date", "fhir_get_slots"}


def test_get_tools_for_agent_skips_entries_without_name():
    """Regression test — this exact bug crashed the app once: an
    mcp_toolset entry has no 'name' key, only 'mcp_server_name'."""
    all_tools = [
        {"name": "calculate_age"},
        {"type": "mcp_toolset", "mcp_server_name": "stripe"},  # no "name" key
    ]
    # Should not raise KeyError
    result = orchestrator.get_tools_for_agent("identity", all_tools)
    assert result == [{"name": "calculate_age"}]


def test_routing_agent_has_no_tools():
    assert orchestrator.AGENTS["routing"]["tools"] == []



def test_build_system_prompt_includes_agent_specific_instructions():
    prompt = orchestrator.build_system_prompt("scheduling")
    assert "fhir_get_slots" in prompt
    assert "MANDATORY" in prompt
    # Shouldn't leak another agent's instructions
    assert "create_payment_link" not in prompt


def test_build_system_prompt_falls_back_to_identity_for_unknown_agent():
    prompt = orchestrator.build_system_prompt("not_a_real_agent")
    identity_prompt = orchestrator.build_system_prompt("identity")
    assert prompt == identity_prompt