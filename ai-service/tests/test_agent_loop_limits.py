"""Tests for the explicit LangGraph Agent-Loop step budget."""

from types import SimpleNamespace

import pytest
from langgraph.errors import GraphRecursionError

import main as main_mod


def test_graph_config_includes_thread_and_explicit_recursion_limit():
    config = main_mod._graph_config("session-123")

    assert config["configurable"]["thread_id"] == "session-123"
    assert config["recursion_limit"] == main_mod.AGENT_RECURSION_LIMIT
    assert config["recursion_limit"] >= 4


def test_graph_recursion_error_is_converted_to_application_error(monkeypatch):
    class LoopingGraph:
        def invoke(self, input_state, config):
            raise GraphRecursionError("limit reached")

    monkeypatch.setattr(main_mod, "admission_graph", LoopingGraph())

    with pytest.raises(main_mod.AgentLoopLimitError) as exc_info:
        main_mod._invoke_admission_graph(
            {"messages": []},
            main_mod._graph_config("session-loop"),
        )

    assert "exceeded" in str(exc_info.value)


def test_session_entrypoints_reset_completion_guard_retry_budget(monkeypatch):
    captured_inputs = []

    def fake_invoke(input_state, config):
        captured_inputs.append(input_state)
        return input_state

    monkeypatch.setattr(main_mod, "_invoke_admission_graph", fake_invoke)
    monkeypatch.setattr(main_mod, "_touch_session", lambda session_id, owner_user_id: None)

    main_mod.start_session(
        "session-new",
        "招生 具备 Python 基础的硕士生",
        owner_user_id=7,
    )

    class ExistingGraph:
        def get_state(self, config):
            return SimpleNamespace(values={"owner_user_id": 7})

    class ActivityConnection:
        def execute(self, sql, params):
            return self

        def fetchone(self):
            return (7,)

    monkeypatch.setattr(main_mod, "admission_graph", ExistingGraph())
    monkeypatch.setattr(main_mod, "_checkpoint_conn", ActivityConnection())

    main_mod.refine_session(
        "session-existing",
        "增加 Kubernetes 要求",
        owner_user_id=7,
    )

    assert [item["completion_guard_retries"] for item in captured_inputs] == [0, 0]
