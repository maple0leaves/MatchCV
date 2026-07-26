"""Tests for api.server._extract_adjustment_note。"""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from api.server import _extract_adjustment_note


def _update_tool_message(call_id: str, change_summary: str, skills: list[str]) -> ToolMessage:
    payload = {
        "jd_info": {
            "title": "Java 工程师",
            "skills": skills,
            "education_requirement": "",
            "description": "",
        },
        "change_summary": change_summary,
    }
    return ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=call_id)


def test_no_adjustment_note_when_update_job_requirements_not_called():
    """纯问答/换方向分支：这一轮完全没有调用 update_job_requirements，应返回 None，
    前端抽屉不展示任何说明，跟改造前行为一致。"""
    result = {
        "messages": [
            HumanMessage(content="按分数重新排一下"),
            AIMessage(content="已按分数从高到低排列，张三 90 分排第一。"),
        ]
    }
    assert _extract_adjustment_note(result) is None


def test_adjustment_note_returns_change_summary_when_full_flow_completed():
    """正常完整流程：调用了 update_job_requirements，也调用了 score_candidates_batch，
    应返回 LLM 写的 change_summary，供前端"调整结果"抽屉展示。"""
    result = {
        "messages": [
            HumanMessage(content="还要会 Kubernetes"),
            AIMessage(
                content="",
                tool_calls=[{"name": "update_job_requirements", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            _update_tool_message("1", "新增技能要求：Kubernetes", ["Java", "Kubernetes"]),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_candidates", "args": {}, "id": "2", "type": "tool_call"}],
            ),
            ToolMessage(content=json.dumps([]), tool_call_id="2"),
            AIMessage(
                content="",
                tool_calls=[{"name": "score_candidates_batch", "args": {}, "id": "3", "type": "tool_call"}],
            ),
            ToolMessage(content=json.dumps([]), tool_call_id="3"),
            AIMessage(content="根据新标准重新匹配完成。"),
        ]
    }
    assert _extract_adjustment_note(result) == "新增技能要求：Kubernetes"


def test_adjustment_note_warns_when_agent_stops_after_updating_requirements_only():
    """边界情况（你要求覆盖的场景）：Agent 调用了 update_job_requirements，但没有
    接着调用 score_candidates_batch。必须返回一句"仍是调整前结果"的提示，而不是
    None（会让前端误以为这轮反馈啥也没干）——这句提示要如实对应
    tool_executor_node 里"清空推迟到 score_candidates_batch 才做"的设计，此时
    match_results 确实还是调整前的旧结果，不是编造的话术。"""
    result = {
        "messages": [
            HumanMessage(content="还要会 Kubernetes"),
            AIMessage(
                content="",
                tool_calls=[{"name": "update_job_requirements", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            _update_tool_message("1", "新增技能要求：Kubernetes", ["Java", "Kubernetes"]),
            AIMessage(content="已更新岗位要求。"),
        ]
    }
    note = _extract_adjustment_note(result)
    assert note is not None
    assert "新增技能要求：Kubernetes" in note
    assert "未完成" in note


def test_adjustment_note_falls_back_to_generic_text_when_change_summary_missing():
    """change_summary 解析失败（工具返回内容不是合法 JSON）时，仍要给出一句
    兜底提示，而不是让整个响应因为字符串拼接报错而崩溃。"""
    result = {
        "messages": [
            HumanMessage(content="还要会 Kubernetes"),
            AIMessage(
                content="",
                tool_calls=[{"name": "update_job_requirements", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            ToolMessage(content="不是合法 JSON", tool_call_id="1"),
            AIMessage(
                content="",
                tool_calls=[{"name": "score_candidates_batch", "args": {}, "id": "2", "type": "tool_call"}],
            ),
            ToolMessage(content=json.dumps([]), tool_call_id="2"),
        ]
    }
    note = _extract_adjustment_note(result)
    assert note == "期望条件已更新，学生已按新标准重新匹配。"
