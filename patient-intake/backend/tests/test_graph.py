"""
tests/test_graph.py — Unit tests for the LangGraph implementation.

Mocks anthropic_client.messages.create entirely — no real API calls, no
cost, no network. Verifies the actual state-machine behavior (redirects,
self-redirect rejection, guard-triggered corrections, multi-message
conversation continuity) BEFORE ever running a real conversation through
the chat interface.

Each simulated "patient message" is its own separate graph.ainvoke() call
with the SAME thread_id — exactly how the real API layer works — rather
than LangGraph's interrupt()/Command(resume=...), which we deliberately
do NOT use (see graph.py's module docstring for why: interrupt()
re-executes all prior node code on every resume, which would silently
re-bill real API calls).

Run with:
    python -m pytest tests/test_graph.py -v
"""
import sys
import os
import asyncio
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langgraph.checkpoint.memory import MemorySaver
import graph as graph_module
from services import orchestrator


def _run(g, state, config):
    """Runs the graph's async API from a plain sync test function."""
    return asyncio.run(g.ainvoke(state, config=config))


def _text_block(text):
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _mock_response(stop_reason, text=None):
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = [_text_block(text)] if text is not None else []
    return resp


def _mock_tool_use_response(tool_name, tool_input, tool_id="tool_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


def _fresh_graph():
    return graph_module.build_graph(checkpointer=MemorySaver())


def _initial_state(session_id="test-session"):
    return {
        "messages": [{"role": "user", "content": "begin"}],
        "current_agent": "identity",
        "return_to": None,
        "slots_ever_called": False,
        "routing_turns_without_redirect": 0,
        "session_id": session_id,
        "lookup_count": 0,
        "just_redirected": False,
        "status": None,
        "final_reply": None,
        "data": None,
        "payment": None,
        "payment_url": None,
    }


class TestRedirectHandling:
    @patch("graph.anthropic_client")
    def test_valid_redirect_moves_to_next_agent_same_invocation(self, mock_client):
        """identity -> insurance redirect happens WITHIN one invocation —
        insurance's own first turn (a real question) is what actually
        ends this invocation, not the redirect itself."""
        mock_client.messages.create.side_effect = [
            _mock_response("end_turn", '{"redirect": "insurance", "reason": "identity complete"}'),
            _mock_response("end_turn", "You have Cigna on file — is that still current?"),
        ]
        g = _fresh_graph()
        config = {"configurable": {"thread_id": "t1"}}
        result = _run(g, _initial_state(), config)

        assert result["final_reply"] == "You have Cigna on file — is that still current?"
        assert result["current_agent"] == "insurance"

    @patch("graph.anthropic_client")
    def test_self_redirect_is_rejected_and_retried(self, mock_client):
        """identity redirecting to itself must be rejected — retried
        internally (a second mocked call) rather than accepted."""
        mock_client.messages.create.side_effect = [
            _mock_response("end_turn", '{"redirect": "identity", "reason": "oops"}'),
            _mock_response("end_turn", '{"redirect": "insurance", "reason": "identity complete"}'),
            _mock_response("end_turn", "You have Cigna on file — is that still current?"),
        ]
        g = _fresh_graph()
        config = {"configurable": {"thread_id": "t2"}}
        result = _run(g, _initial_state(), config)

        assert result["current_agent"] == "insurance"
        assert any(
            "ALREADY the" in str(m["content"])
            for m in result["messages"] if m["role"] == "user"
        )


class TestSchedulingGuards:
    @patch("graph.call_tool")
    @patch("graph.anthropic_client")
    def test_asking_before_tool_call_triggers_correction(self, mock_client, mock_call_tool):
        """Scheduling agent asking a day/time preference BEFORE calling
        fhir_get_slots gets rejected and corrected. After the correction,
        a REAL tool call happens — only then can real slots be presented
        without being flagged as fabricated (slots_ever_called becomes
        True at that point, same as the original claude.py behavior)."""
        async def fake_call_tool(name, input):
            return '{"slots": [{"doctor": "Dr. Patel", "date": "Mon", "time": "9:00 AM"}]}'
        mock_call_tool.side_effect = fake_call_tool

        mock_client.messages.create.side_effect = [
            _mock_response("end_turn", "What day works best for you?"),
            _mock_tool_use_response("fhir_get_slots", {"department": "Family Medicine"}),
            _mock_response("end_turn", "Here are some real slots: 1. Dr. Patel — Mon at 9:00 AM"),
        ]
        state = _initial_state()
        state["current_agent"] = "scheduling"
        g = _fresh_graph()
        config = {"configurable": {"thread_id": "t3"}}
        result = _run(g, state, config)

        assert result["final_reply"] == "Here are some real slots: 1. Dr. Patel — Mon at 9:00 AM"
        assert result["slots_ever_called"] is True
        assert mock_client.messages.create.call_count == 3


class TestMultiTurnConversation:
    @patch("graph.anthropic_client")
    def test_two_separate_chat_messages_continue_correctly(self, mock_client):
        """Simulates two real, separate patient messages as two separate
        graph.ainvoke() calls (same thread_id) — exactly how the real API
        layer works. No interrupt()/Command(resume=...) involved."""
        mock_client.messages.create.side_effect = [
            _mock_response("end_turn", "Are you a new or returning patient?"),
            _mock_response("end_turn", '{"redirect": "insurance", "reason": "identity complete"}'),
            _mock_response("end_turn", "You have Cigna on file — is that still current?"),
        ]
        g = _fresh_graph()
        config = {"configurable": {"thread_id": "t4"}}

        first = _run(g, _initial_state(), config)
        assert first["final_reply"] == "Are you a new or returning patient?"
        assert first["current_agent"] == "identity"

        # A second, entirely separate invocation — this is exactly what
        # the API layer does for the next real chat message: append the
        # new user message and invoke again with the SAME thread_id.
        second_state = dict(first)
        second_state["messages"] = first["messages"] + [
            {"role": "user", "content": "Returning patient"}
        ]
        second = _run(g, second_state, config)

        assert second["final_reply"] == "You have Cigna on file — is that still current?"
        assert second["current_agent"] == "insurance"
        assert any(
            m["role"] == "user" and m["content"] == "Returning patient"
            for m in second["messages"]
        )
        # Confirm the FIRST call's mocked responses were only consumed
        # once total across both invocations — proving no re-execution
        # or re-billing happened.
        assert mock_client.messages.create.call_count == 3


class TestTerminalStatus:
    @patch("graph.anthropic_client")
    def test_completion_status_reaches_end(self, mock_client):
        """A {"status": "complete", ...} signal should end the graph
        rather than waiting for another patient reply."""
        completion_json = (
            'All set! '
            '{"status": "complete", "data": {"name": "Test Patient", "copay": "25", '
            '"appointment_doctor": "Dr. Patel", "appointment_date": "Mon", '
            '"appointment_time": "9:00 AM"}, "payment": "later"}'
        )
        mock_client.messages.create.side_effect = [
            _mock_response("end_turn", completion_json),
        ]
        state = _initial_state()
        state["current_agent"] = "payment"
        g = _fresh_graph()
        config = {"configurable": {"thread_id": "t5"}}
        result = _run(g, state, config)

        assert result["status"] == "complete"
        assert result["data"]["name"] == "Test Patient"
        assert result["payment"] == "later"