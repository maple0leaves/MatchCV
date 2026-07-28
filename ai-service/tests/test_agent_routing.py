"""Tests for the single-agent routing decisions (R1-2 / R1-6) and the tool
executor's server-side guarantees (L1 top_k enforcement, L3 student profile
passthrough)."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages

import agent.agent as agent_mod
from agent.agent import (
    _build_match_results_context,
    _completion_guard_issue,
    _llm_calibrate_score,
    _local_match_score,
    _select_recent_rounds,
    _validate_search_result,
    compress_node,
    route_from_agent,
    tool_executor_node,
)
from agent.schemas import StudentProfile, AdmissionCriteria, MatchResult, AdmissionInput


def test_route_from_agent_to_end_when_no_tool_calls():
    state = {"messages": [AIMessage(content="请补充招收方向或核心技能要求")]}
    assert route_from_agent(state) == "__end__"


def test_route_from_agent_to_tools_when_tool_calls_present():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_students", "args": {"query": "python"}, "id": "1", "type": "tool_call"}],
            )
        ]
    }
    assert route_from_agent(state) == "tools"


def _tool_call_message(name: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": name,
            "args": {},
            "id": call_id,
            "type": "tool_call",
        }],
    )


def _tool_result_message(call_id: str, content: str = "{}") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id)


def test_completion_guard_requires_search_for_sufficient_first_request():
    state = {"messages": [HumanMessage(content="招生 具备 Python 基础的硕士生")]}
    admission_criteria = AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"])

    issue = _completion_guard_issue(state, admission_criteria)

    assert issue is not None
    assert "search_students" in issue


def test_completion_guard_allows_clarification_for_insufficient_first_request():
    state = {"messages": [HumanMessage(content="帮我找个人")]}

    assert _completion_guard_issue(state, AdmissionCriteria()) is None


def test_completion_guard_requires_score_after_search():
    state = {
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message(
                "search-1",
                '{"status":"ok","student_count":0}',
            ),
        ]
    }

    issue = _completion_guard_issue(
        state,
        AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
    )

    assert issue is not None
    assert "score_students_batch" in issue


def test_completion_guard_requires_score_after_requirement_update():
    state = {
        "messages": [
            HumanMessage(content="增加 Kubernetes 要求"),
            _tool_call_message("search_students", "search-old"),
            _tool_result_message("search-old"),
            _tool_call_message("score_students_batch", "score-old"),
            _tool_result_message("score-old"),
            _tool_call_message("update_admission_criteria", "update-1"),
            _tool_result_message("update-1"),
        ]
    }

    issue = _completion_guard_issue(
        state,
        AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python", "Kubernetes"]),
    )

    assert issue is not None
    assert "更新后" in issue
    assert "score_students_batch" in issue


def test_completion_guard_accepts_rescoring_existing_students_after_update():
    state = {
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            AIMessage(content="初次匹配完成"),
            HumanMessage(content="学历要求提高到硕士"),
            _tool_call_message("update_admission_criteria", "update-1"),
            _tool_result_message("update-1"),
            _tool_call_message("score_students_batch", "score-1"),
            _tool_result_message("score-1"),
        ]
    }

    assert _completion_guard_issue(
        state,
        AdmissionCriteria(
            title="具备 Python 基础的硕士生",
            skills=["Python"],
            education_requirement="硕士",
        ),
    ) is None


def test_completion_guard_accepts_complete_update_search_score_chain():
    state = {
        "messages": [
            HumanMessage(content="增加 Kubernetes 要求"),
            _tool_call_message("update_admission_criteria", "update-1"),
            _tool_result_message("update-1"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message("search-1"),
            _tool_call_message("score_students_batch", "score-1"),
            _tool_result_message("score-1"),
        ]
    }

    assert _completion_guard_issue(
        state,
        AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python", "Kubernetes"]),
    ) is None


def test_completion_guard_allows_direct_answer_in_later_round():
    state = {
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            AIMessage(content="匹配完成"),
            HumanMessage(content="前三名是谁？"),
        ]
    }

    assert _completion_guard_issue(
        state,
        AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
    ) is None


def test_agent_completion_guard_repairs_once_when_agent_ends_early(monkeypatch):
    calls = []
    responses = [
        AIMessage(content="匹配完成"),
        _tool_call_message("score_students_batch", "score-repair"),
    ]

    class FakeAgentLLM:
        def invoke(self, messages):
            calls.append(messages)
            return responses.pop(0)

    monkeypatch.setattr(agent_mod, "_llm_with_tools", FakeAgentLLM())
    state = {
        "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
        "match_results": [],
        "completion_guard_retries": 0,
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message("search-1"),
        ],
    }

    result = agent_mod.agent_node(state)

    assert len(calls) == 2
    assert result["completion_guard_retries"] == 1
    assert result["messages"][0].tool_calls[0]["name"] == "score_students_batch"
    assert "第 1/2 次内部补救" in calls[1][0]["content"]


def test_agent_completion_guard_raises_after_two_failed_repairs(monkeypatch):
    calls = []

    class FakeAgentLLM:
        def invoke(self, messages):
            calls.append(messages)
            return AIMessage(content="匹配完成")

    monkeypatch.setattr(agent_mod, "_llm_with_tools", FakeAgentLLM())
    state = {
        "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
        "match_results": [],
        "completion_guard_retries": 0,
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message("search-1"),
        ],
    }

    with pytest.raises(agent_mod.AgentWorkflowIncompleteError):
        agent_mod.agent_node(state)

    assert len(calls) == 3


def test_agent_completion_guard_allows_second_repair_in_same_round(monkeypatch):
    calls = []
    responses = [
        AIMessage(content="匹配完成"),
        _tool_call_message("score_students_batch", "score-repair-2"),
    ]

    class FakeAgentLLM:
        def invoke(self, messages):
            calls.append(messages)
            return responses.pop(0)

    monkeypatch.setattr(agent_mod, "_llm_with_tools", FakeAgentLLM())
    state = {
        "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
        "match_results": [],
        "completion_guard_retries": 1,
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message("search-1"),
        ],
    }

    result = agent_mod.agent_node(state)

    assert len(calls) == 2
    assert result["completion_guard_retries"] == 2
    assert result["messages"][0].tool_calls[0]["name"] == "score_students_batch"
    assert "第 2/2 次内部补救" in calls[1][0]["content"]


def test_agent_completion_guard_does_not_retry_after_budget_is_exhausted(monkeypatch):
    calls = []

    class FakeAgentLLM:
        def invoke(self, messages):
            calls.append(messages)
            return AIMessage(content="匹配完成")

    monkeypatch.setattr(agent_mod, "_llm_with_tools", FakeAgentLLM())
    state = {
        "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
        "match_results": [],
        "completion_guard_retries": 2,
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message("search-1"),
        ],
    }

    with pytest.raises(agent_mod.AgentWorkflowIncompleteError):
        agent_mod.agent_node(state)

    assert len(calls) == 1


def test_agent_completion_guard_adds_no_call_for_complete_flow(monkeypatch):
    calls = []

    class FakeAgentLLM:
        def invoke(self, messages):
            calls.append(messages)
            return AIMessage(content="匹配完成")

    monkeypatch.setattr(agent_mod, "_llm_with_tools", FakeAgentLLM())
    state = {
        "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
        "match_results": [],
        "completion_guard_retries": 0,
        "messages": [
            HumanMessage(content="招生 具备 Python 基础的硕士生"),
            _tool_call_message("search_students", "search-1"),
            _tool_result_message("search-1"),
            _tool_call_message("score_students_batch", "score-1"),
            _tool_result_message("score-1"),
        ],
    }

    result = agent_mod.agent_node(state)

    assert len(calls) == 1
    assert "completion_guard_retries" not in result
    assert result["messages"][0].content == "匹配完成"


def test_search_students_top_k_is_enforced_from_session_state(monkeypatch):
    """L1: top_k 必须由会话状态强制生效，不能由 LLM 自己传的参数决定。"""
    captured_args = {}

    class FakeSearchTool:
        def invoke(self, args):
            captured_args.update(args)
            return json.dumps([])

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "search_students", FakeSearchTool())

    state = {
        "owner_user_id": 42,
        "match_top_k": 7,
        "admission_criteria": None,
        "students": [],
        "match_results": [],
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_students",

                        "args": {"query": "python", "top_k": 999},
                        "id": "1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
    }
    tool_executor_node(state)

    assert captured_args["top_k"] == 7
    assert captured_args["owner_user_id"] == 42


def test_validate_search_result_accepts_empty_list():
    normalized, count = _validate_search_result("[]")

    assert normalized == "[]"
    assert count == 0


def test_validate_search_result_normalizes_student_text_fields():
    normalized, count = _validate_search_result(json.dumps([{
        "name": 123,
        "email": None,
        "source": "resume.pdf",
        "content": None,
        "extra": "kept",
    }]))

    student = json.loads(normalized)[0]
    assert count == 1
    assert student["name"] == "123"
    assert student["email"] == ""
    assert student["content"] == ""
    assert student["extra"] == "kept"


@pytest.mark.parametrize(
    "raw_result",
    [
        "not-json",
        json.dumps({"name": "张三"}),
        json.dumps(["not-an-object"]),
        json.dumps([{"name": "张三", "source": "", "content": ""}]),
    ],
)
def test_validate_search_result_rejects_malformed_payloads(raw_result):
    with pytest.raises(agent_mod.SearchResultValidationError):
        _validate_search_result(raw_result)


def test_select_recent_rounds_keeps_last_three_complete_rounds():
    messages = []
    for index in range(1, 5):
        messages.extend([
            HumanMessage(content=f"第{index}轮", id=f"h-{index}"),
            AIMessage(content=f"第{index}轮完成", id=f"a-{index}"),
        ])

    selected = _select_recent_rounds(messages)

    assert [
        message.content for message in selected if isinstance(message, HumanMessage)
    ] == ["第2轮", "第3轮", "第4轮"]
    assert selected[0].id == "h-2"


def test_compress_node_rebuilds_window_without_breaking_tool_pairs():
    messages = [
        HumanMessage(content="第1轮", id="h-1"),
        AIMessage(content="第1轮完成", id="a-1"),
        HumanMessage(content="第2轮", id="h-2"),
        AIMessage(content="第2轮完成", id="a-2"),
        HumanMessage(content="第3轮", id="h-3"),
        AIMessage(content="第3轮完成", id="a-3"),
        HumanMessage(content="第4轮", id="h-4"),
        AIMessage(
            content="",
            id="a-search",
            tool_calls=[{
                "name": "search_students",
                "args": {"query": "python"},
                "id": "call-search",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=json.dumps([{"name": "张三"}], ensure_ascii=False),
            tool_call_id="call-search",
            id="tm-search",
        ),
        AIMessage(
            content="",
            id="a-score",
            tool_calls=[{
                "name": "score_students_batch",
                "args": {},
                "id": "call-score",
                "type": "tool_call",
            }],
        ),
        ToolMessage(
            content=json.dumps([{"student_name": "张三", "match_score": 90}]),
            tool_call_id="call-score",
            id="tm-score",
        ),
        AIMessage(content="第4轮完成", id="a-4"),
    ]

    result = compress_node({"messages": messages})

    assert isinstance(result["messages"][0], RemoveMessage)
    assert result["messages"][0].id == REMOVE_ALL_MESSAGES
    merged = add_messages(messages, result["messages"])
    assert [message.id for message in merged[:2]] == ["h-2", "a-2"]
    assert all(message.id not in {"h-1", "a-1"} for message in merged)

    search_index = next(i for i, message in enumerate(merged) if message.id == "a-search")
    assert merged[search_index + 1].id == "tm-search"
    assert merged[search_index + 1].tool_call_id == "call-search"
    score_index = next(i for i, message in enumerate(merged) if message.id == "a-score")
    assert merged[score_index + 1].id == "tm-score"
    assert merged[score_index + 1].tool_call_id == "call-score"


def test_compress_node_is_noop_within_round_limit():
    state = {
        "messages": [
            HumanMessage(content="第1轮"),
            AIMessage(content="第1轮完成"),
            HumanMessage(content="第2轮"),
            AIMessage(content="第2轮完成"),
            HumanMessage(content="第3轮"),
            AIMessage(content="第3轮完成"),
        ]
    }

    assert compress_node(state) == {}


def test_agent_uses_window_and_structured_match_context(monkeypatch):
    captured = {}

    class FakeAgentLLM:
        def invoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="完成")

    monkeypatch.setattr(agent_mod, "_llm_with_tools", FakeAgentLLM())
    history = []
    for index in range(1, 5):
        history.extend([
            HumanMessage(content=f"第{index}轮", id=f"h-{index}"),
            AIMessage(content=f"第{index}轮完成", id=f"a-{index}"),
        ])
    state = {
        "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"]),
        "match_results": [
            MatchResult(
                student_name="张三",
                match_score=90,
                matched_skills=["Python", "FastAPI"],
                missing_skills=["Kubernetes"],
                recommendation="技术背景匹配",
            )
        ],
        "messages": history,
    }

    agent_mod.agent_node(state)

    system_content = captured["messages"][0]["content"]
    assert "张三" in system_content
    assert '"match_score":90' in system_content
    assert [
        message.content
        for message in captured["messages"][1:]
        if isinstance(message, HumanMessage)
    ] == ["第2轮", "第3轮", "第4轮"]
    assert "张三" in _build_match_results_context(state)


def test_tool_executor_persists_search_result_for_cross_round_reuse(monkeypatch):
    """search_students 的真实结果要写进 state["last_search_result_json"]，
    不能只留在 messages 里——旧轮次可能在滑动窗口推进后被整体移除。"""
    fake_result = json.dumps([{"name": "张三", "source": "a.pdf", "content": "..."}], ensure_ascii=False)

    class FakeSearchTool:
        def invoke(self, args):
            return fake_result

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "search_students", FakeSearchTool())

    state = {
        "owner_user_id": 42,
        "match_top_k": 5,
        "admission_criteria": None,
        "students": [],
        "match_results": [],
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_students", "args": {"query": "python"}, "id": "1", "type": "tool_call"}],
            )
        ],
    }

    result = tool_executor_node(state)

    assert result["last_search_result_json"] == fake_result
    observation = json.loads(result["messages"][0]["content"])
    assert observation == {
        "status": "ok",
        "tool": "search_students",
        "student_count": 1,
        "next_action": "call score_students_batch",
    }
    assert "张三" not in result["messages"][0]["content"]
    assert "a.pdf" not in result["messages"][0]["content"]


def test_score_students_batch_reuses_persisted_search_result_without_new_search(monkeypatch):
    """R2 回归防护：多轮反馈里 Agent 只调用 score_students_batch、不重新调用
    search_students 时（"排除某学历"这类反馈），必须能从
    state["last_search_result_json"] 拿到真实学生数据——不能依赖从 messages
    里现读最近一次 search_students 的 ToolMessage（那一轮可能已经滑出窗口）。"""
    captured_args = {}

    class FakeScoreTool:
        def invoke(self, args):
            captured_args.update(args)
            return json.dumps([])

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "score_students_batch", FakeScoreTool())

    persisted_json = json.dumps([{"name": "张三", "source": "a.pdf", "content": "..."}], ensure_ascii=False)
    state = {
        "match_top_k": 5,
        "admission_criteria": None,
        "students": [],
        "match_results": [],
        "last_search_result_json": persisted_json,
        "messages": [


            AIMessage(
                content="",
                tool_calls=[
                    {"name": "score_students_batch", "args": {"students_json": "", "admission_criteria_json": ""}, "id": "2", "type": "tool_call"}
                ],
            )
        ],
    }

    tool_executor_node(state)

    assert captured_args["students_json"] == persisted_json


def test_llm_calibrate_score_truncates_resume_at_configured_char_limit(monkeypatch):
    """简历全文校准调用应该按 SCORE_CALIBRATION_MAX_RESUME_CHARS 截断——曾评估过
    Map-Reduce 分块摘要方案，但 2 页简历基本落在旧阈值(3000字)上下，分块收益
    有限却引入额外复杂度，最终简化为"放宽单次截断上限、不分块"（见
    agent.agent._llm_calibrate_score 的 docstring）。这里验证截断确实按配置的
    字符数生效，且超出部分不会出现在喂给 LLM 的 prompt 里。"""
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_ENABLED", True)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_RULE_WEIGHT", 0.5)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_LLM_WEIGHT", 0.5)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_MAX_RESUME_CHARS", 20)

    captured = {}

    class FakeCalibrator:
        def invoke(self, prompt):
            from agent.schemas import LLMScoreJudgment

            captured["prompt"] = prompt
            return LLMScoreJudgment(score=70, reasoning="ok", resume_summary="")

    monkeypatch.setattr(agent_mod, "_get_score_calibrator", lambda: FakeCalibrator())

    base = MatchResult(student_name="张三", match_score=70, matched_skills=["Python"], missing_skills=[])
    resume_text = "前20字以内的内容ABCDEFGH" + "超出截断上限之后的内容不应该出现在prompt里" * 20
    _llm_calibrate_score(base, admission_criteria=None, resume_text=resume_text)

    assert resume_text[:20] in captured["prompt"]
    assert "超出截断上限之后的内容" not in captured["prompt"]


def test_llm_calibrate_score_blends_rule_and_llm_scores_by_configured_weight(monkeypatch):
    """规则基线分与 LLM 独立打分按默认 70% / 30% 权重加权融合。"""
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_ENABLED", True)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_RULE_WEIGHT", 0.7)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_LLM_WEIGHT", 0.3)

    class FakeCalibrator:
        def invoke(self, prompt):
            from agent.schemas import LLMScoreJudgment

            return LLMScoreJudgment(score=90, reasoning="项目经验突出", resume_summary="摘要")

    monkeypatch.setattr(agent_mod, "_get_score_calibrator", lambda: FakeCalibrator())

    base = MatchResult(student_name="张三", match_score=60, matched_skills=["Python"], missing_skills=[])
    result = _llm_calibrate_score(base, admission_criteria=None, resume_text="简历全文")


    assert result.match_score == 69
    assert result.recommendation == "项目经验突出"


def test_llm_calibrate_score_falls_back_to_rule_score_when_llm_fails(monkeypatch):
    """LLM 调用失败时完全回退规则基线分（相当于规则权重=100%），不能因为单个
    学生的 LLM 调用异常就让整批打分崩掉或分数变成异常值。"""
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_ENABLED", True)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_RULE_WEIGHT", 0.5)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_LLM_WEIGHT", 0.5)

    class FailingCalibrator:
        def invoke(self, prompt):
            raise RuntimeError("boom")

    monkeypatch.setattr(agent_mod, "_get_score_calibrator", lambda: FailingCalibrator())

    base = MatchResult(student_name="张三", match_score=60, matched_skills=["Python"], missing_skills=[])
    result = _llm_calibrate_score(base, admission_criteria=None, resume_text="简历全文")

    assert result.match_score == 60


def test_refine_search_expansion_adds_new_student_without_touching_old_scores(monkeypatch):
    """方向1回归防护：反馈触发"补充检索"（Agent 判断现有学生不够、重新调用
    search_students）时，新学生应该被追加进学生列表，旧学生的打分结果
    必须原样保留、不能被覆盖或丢失——这正是"优化结果"能够真正找到"初次检索
    没覆盖到的学生"的关键：跨轮状态是累加而不是替换。"""
    old_match = MatchResult(student_name="张三", match_score=80, matched_skills=["Java"], missing_skills=[])
    old_student = StudentProfile(name="张三", skills=["Java"], source="zhangsan.pdf")


    new_search_json = json.dumps([{"name": "老王", "source": "laowang.pdf", "content": "Java + Kubernetes 专家"}], ensure_ascii=False)

    class FakeSearchTool:
        def invoke(self, args):
            return new_search_json

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "search_students", FakeSearchTool())

    state_after_search = tool_executor_node({
        "owner_user_id": 42,
        "match_top_k": 5,
        "admission_criteria": None,
        "students": [old_student],
        "match_results": [old_match],
        "last_search_result_json": None,
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_students", "args": {"query": "Java Kubernetes"}, "id": "1", "type": "tool_call"}],
            )
        ],
    })


    assert state_after_search["students"] == [old_student]
    assert state_after_search["match_results"] == [old_match]
    assert state_after_search["last_search_result_json"] == new_search_json


    new_match_json = json.dumps([{
        "student": {"name": "老王", "skills": ["Java", "Kubernetes"], "source": "laowang.pdf"},
        "match_result": {"student_name": "老王", "match_score": 88, "matched_skills": ["Java", "Kubernetes"], "missing_skills": []},
    }])

    class FakeScoreTool:
        def invoke(self, args):
            return new_match_json

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "score_students_batch", FakeScoreTool())

    final_state = tool_executor_node({
        "match_top_k": 5,
        "admission_criteria": None,
        "students": state_after_search["students"],
        "match_results": state_after_search["match_results"],
        "last_search_result_json": state_after_search["last_search_result_json"],
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "score_students_batch", "args": {"students_json": "", "admission_criteria_json": ""}, "id": "2", "type": "tool_call"}],
            )
        ],
    })

    result_names = {m.student_name for m in final_state["match_results"]}
    assert result_names == {"张三", "老王"}

    zhangsan_result = next(m for m in final_state["match_results"] if m.student_name == "张三")
    assert zhangsan_result.match_score == 80
    laowang_result = next(m for m in final_state["match_results"] if m.student_name == "老王")
    assert laowang_result.match_score == 88


def test_update_admission_criteria_only_updates_admission_criteria_leaves_students_untouched(monkeypatch):
    """update_admission_criteria
    执行时只应该更新 admission_criteria，绝不碰 students/match_results/last_search_result_json。
    "清空旧数据"这个动作被推迟到 score_students_batch 真正执行时才做——这样即使
    Agent 调用完这个工具后没有按预期继续检索/打分，前端也不会看到空列表。"""
    old_match = MatchResult(student_name="张三", match_score=80, matched_skills=["Java"], missing_skills=[])
    old_student = StudentProfile(name="张三", skills=["Java"], source="zhangsan.pdf")
    old_admission_criteria = AdmissionCriteria(title="Java 工程师", skills=["Java"])

    update_result_json = json.dumps(
        {
            "admission_criteria": {
                "title": "Java 工程师",
                "skills": ["Java", "Kubernetes"],
                "education_requirement": "",
                "description": "",
            },
            "change_summary": "新增技能要求：Kubernetes",
        },
        ensure_ascii=False,
    )

    class FakeUpdateTool:
        def invoke(self, args):
            return update_result_json

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "update_admission_criteria", FakeUpdateTool())

    state = {
        "match_top_k": 5,
        "admission_criteria": old_admission_criteria,
        "students": [old_student],
        "match_results": [old_match],
        "last_search_result_json": "old-search-json",
        "messages": [
            HumanMessage(content="不再要求消息队列，还要会 Kubernetes"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "update_admission_criteria", "args": {"admission_criteria_json": "", "feedback_text": ""}, "id": "1", "type": "tool_call"}
                ],
            ),
        ],
    }

    result = tool_executor_node(state)

    assert result["admission_criteria"].skills == ["Java", "Kubernetes"]
    assert result["students"] == [old_student]
    assert result["match_results"] == [old_match]
    assert result["last_search_result_json"] == "old-search-json"


def test_score_students_batch_fully_replaces_results_when_requirements_updated_this_round(monkeypatch):
    """这一轮更早调用过
    update_admission_criteria 时，score_students_batch 必须清空旧的
    student_map/match_map，用这批新打分结果整体替换旧列表——不能沿用"只重新
    打分已有学生"场景的合并/覆盖语义，否则旧标准下淘汰的学生会一直赖在
    列表里。"""
    old_match = MatchResult(student_name="张三", match_score=80, matched_skills=["Java"], missing_skills=[])
    old_student = StudentProfile(name="张三", skills=["Java"], source="zhangsan.pdf")

    new_match_json = json.dumps(
        [
            {
                "student": {"name": "李四", "skills": ["Java", "Kubernetes"], "source": "lisi.pdf"},
                "match_result": {
                    "student_name": "李四",
                    "match_score": 92,
                    "matched_skills": ["Java", "Kubernetes"],
                    "missing_skills": [],
                },
            }
        ]
    )

    class FakeScoreTool:
        def invoke(self, args):
            return new_match_json

    monkeypatch.setitem(agent_mod.TOOLS_BY_NAME, "score_students_batch", FakeScoreTool())

    search_json = json.dumps([{"name": "李四", "source": "lisi.pdf", "content": "..."}], ensure_ascii=False)
    update_json = json.dumps(
        {
            "admission_criteria": {
                "title": "Java 工程师",
                "skills": ["Java", "Kubernetes"],
                "education_requirement": "",
                "description": "",
            },
            "change_summary": "新增技能要求：Kubernetes",
        },
        ensure_ascii=False,
    )

    state = {
        "match_top_k": 5,
        "admission_criteria": AdmissionCriteria(title="Java 工程师", skills=["Java", "Kubernetes"]),
        "students": [old_student],
        "match_results": [old_match],
        "last_search_result_json": search_json,
        "messages": [
            HumanMessage(content="还要会 Kubernetes"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "update_admission_criteria", "args": {"admission_criteria_json": "", "feedback_text": ""}, "id": "1", "type": "tool_call"}
                ],
            ),
            ToolMessage(content=update_json, tool_call_id="1"),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_students", "args": {"query": "Java Kubernetes"}, "id": "2", "type": "tool_call"}],
            ),
            ToolMessage(content=search_json, tool_call_id="2"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "score_students_batch", "args": {"students_json": "", "admission_criteria_json": ""}, "id": "3", "type": "tool_call"}
                ],
            ),
        ],
    }

    result = tool_executor_node(state)

    result_names = {m.student_name for m in result["match_results"]}
    assert result_names == {"李四"}
    assert [c.name for c in result["students"]] == ["李四"]


def test_local_match_score_carries_student_education():
    """学历随匹配结果返回，供页面展示和评分解释使用。"""
    student = StudentProfile(
        name="张三",
        skills=["Python"],
        education="硕士",
    )
    admission_criteria = AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python"])

    match_result = _local_match_score(student, admission_criteria, resume_text="Python 硕士")

    assert match_result.education == "硕士"


@pytest.mark.parametrize(
    ("resume_text", "expected"),
    [
        (
            "人工智能专业本科在读，计划申请 2027 年秋季人工智能硕士。",
            "本科",
        ),
        (
            "计划申请人工智能硕士\n教育背景\n华南理工大学 人工智能 工学学士",
            "本科",
        ),
        (
            "计算机科学硕士研究生在读，拟申请人工智能方向博士研究生。",
            "硕士",
        ),
        (
            "B.Sc. in Artificial Intelligence. Applying for a Master's in AI.",
            "本科",
        ),
        (
            "计划申请人工智能硕士研究生。",
            "",
        ),
        (
            "人工智能专业本科在读，申请材料准备中。",
            "本科",
        ),
    ],
)
def test_extract_education_ignores_application_target(resume_text, expected):
    """申请目标不是已经取得或正在就读的学历。"""
    assert agent_mod._extract_education(resume_text) == expected


def test_master_admission_normalization_separates_target_degree_and_rule_skills():
    """硕士是申请目标；当前学历默认为本科，定性条件不能混入技能规则。"""
    parsed = AdmissionCriteria(
        title="多模态大模型方向硕士研究生",
        skills=[
            "Python",
            "PyTorch",
            "计算机视觉",
            "自然语言处理",
            "科研经历",
            "项目经历",
            "课程设计",
            "论文",
            "竞赛",
            "开源项目",
            "可验证实验成果",
            "英语优秀",
            "数学优秀",
            "数学建模",
        ],
        education_requirement="硕士/博士研究生",
        description="完整期望条件",
    )

    normalized = agent_mod._normalize_master_admission_criteria(
        parsed,
        "招收方向：多模态大模型方向硕士\n期望条件：希望学生具备相关能力",
    )

    assert normalized.education_requirement == "本科"
    assert normalized.skills == [
        "Python",
        "PyTorch",
        "计算机视觉",
        "自然语言处理",
        "数学建模",
    ]
    assert normalized.description == "完整期望条件"


def test_master_admission_normalization_honors_explicit_current_education():
    """用户明确写出的当前学历条件优先于模型从招收方向推断的值。"""
    parsed = AdmissionCriteria(
        title="多模态大模型方向硕士研究生",
        skills=["Python"],
        education_requirement="硕士",
    )

    normalized = agent_mod._normalize_master_admission_criteria(
        parsed,
        "招收方向：多模态大模型方向硕士\n期望条件：学历本科，具备 Python 基础",
    )

    assert normalized.education_requirement == "本科"


def test_admission_input_rejects_doctoral_admission_direction():
    """产品范围只包含硕士申请，博士方向不能进入后续匹配与评分。"""
    with pytest.raises(ValueError, match="当前仅支持硕士研究生申请筛选"):
        AdmissionInput(
            user_input="招收方向：多模态大模型方向博士研究生\n期望条件：学历硕士",
        )


def test_admission_input_accepts_master_admission_direction():
    request = AdmissionInput(
        user_input="招收方向：多模态大模型方向硕士\n期望条件：学历本科",
    )

    assert "硕士" in request.user_input


def test_student_rule_score_uses_skill_60_and_education_40():
    """同时填写技能和学历条件时，规则分严格按技能 60 / 学历 40 计算。"""
    student = StudentProfile(name="张三", skills=["Python"], education="本科")
    admission_criteria = AdmissionCriteria(
        title="多模态大模型方向硕士研究生",
        skills=["Python", "PyTorch"],
        education_requirement="本科",
    )

    result = _local_match_score(student, admission_criteria, resume_text="本科，熟悉 Python")

    assert result.score_breakdown.skill_points == 30
    assert result.score_breakdown.education_points == 40
    assert result.score_breakdown.rule_score == 70
    assert result.match_score == 70


def test_student_rule_score_normalizes_skill_to_100_without_education_requirement():
    """未填写学历条件时不能自动赠送 40 分，技能维度应归一化到 100。"""
    student = StudentProfile(name="张三", skills=["Python"], education="本科")
    admission_criteria = AdmissionCriteria(
        title="多模态大模型方向硕士研究生",
        skills=["Python", "PyTorch"],
    )

    result = _local_match_score(student, admission_criteria, resume_text="本科，熟悉 Python")

    assert result.score_breakdown.skill_points == 50
    assert result.score_breakdown.education_points == 0
    assert result.score_breakdown.rule_score == 50
