"""Tests for candidate-scoped, read-only detail chat."""

import asyncio

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from pydantic import ValidationError

import agent.agent as agent_mod
import agent.candidate_chat as candidate_chat_mod
from agent.agent import _llm_calibrate_score, _local_match_score
from agent.candidate_chat import answer_candidate_question
from agent.schemas import (
    CandidateChatMessage,
    CandidateChatRequest,
    CandidateInfo,
    JDInfo,
    LLMScoreJudgment,
    MatchResult,
    ScoreBreakdown,
)


def _match_result(source: str = "candidate-a.pdf") -> MatchResult:
    return MatchResult(
        candidate_name="张三",
        match_score=82,
        matched_skills=["Python"],
        missing_skills=["Kubernetes"],
        recommendation="Python 项目经验与岗位相关",
        resume_source=source,
        resume_text="张三，使用 Python 参与知识问答系统建设。",
        education="本科",
        summary="参与 Python 知识问答项目。",
    )


def test_local_score_records_reusable_score_breakdown():
    result = _local_match_score(
        CandidateInfo(
            name="张三",
            skills=["Python"],
            education="本科",
        ),
        JDInfo(
            title="人工智能方向硕士研究生",
            skills=["Python", "Docker"],
            education_requirement="本科",
        ),
        resume_text="Python 项目经验",
    )

    assert result.match_score == 70
    assert result.score_breakdown.skill_points == 30
    assert result.score_breakdown.education_points == 40
    assert result.score_breakdown.rule_score == 70
    assert result.score_breakdown.final_score == 70
    assert result.score_breakdown.calibration_status == "disabled"


def test_legacy_match_result_does_not_invent_missing_score_breakdown():
    result = MatchResult(candidate_name="旧会话候选人", match_score=82)

    assert result.score_breakdown.rule_score is None
    assert result.score_breakdown.llm_score is None
    assert result.score_breakdown.final_score == 82
    assert result.score_breakdown.calibration_status == "unavailable"


def test_llm_calibration_records_score_weights_and_status(monkeypatch):
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_ENABLED", True)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_RULE_WEIGHT", 0.7)
    monkeypatch.setattr(agent_mod, "SCORE_CALIBRATION_LLM_WEIGHT", 0.3)

    class FakeCalibrator:
        def invoke(self, _prompt):
            return LLMScoreJudgment(score=90, reasoning="语义匹配较好")

    monkeypatch.setattr(agent_mod, "_get_score_calibrator", lambda: FakeCalibrator())

    result = _llm_calibrate_score(
        MatchResult(candidate_name="张三", match_score=60),
        jd_info=None,
        resume_text="Python",
    )

    assert result.match_score == 69
    assert result.score_breakdown.rule_score == 60
    assert result.score_breakdown.llm_score == 90
    assert result.score_breakdown.rule_weight == 0.7
    assert result.score_breakdown.llm_weight == 0.3
    assert result.score_breakdown.final_score == 69
    assert result.score_breakdown.calibration_status == "success"


def test_candidate_chat_request_rejects_more_than_eight_history_messages():
    history = [
        {"role": "user", "content": f"问题 {index}"}
        for index in range(9)
    ]

    with pytest.raises(ValidationError):
        CandidateChatRequest(
            session_id="session-a",
            resume_source="candidate-a.pdf",
            message="为什么推荐？",
            history=history,
        )


def test_candidate_chat_uses_bounded_history_and_authoritative_context(monkeypatch):
    captured = {}

    class FakeLlm:
        def invoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="推荐依据是 Python 经历。")

    monkeypatch.setattr(candidate_chat_mod, "_llm", FakeLlm())
    history = [
        CandidateChatMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"history-{index}",
        )
        for index in range(10)
    ]

    answer = answer_candidate_question(
        JDInfo(title="Python 工程师", skills=["Python", "Kubernetes"]),
        _match_result(),
        history,
        "为什么推荐？",
    )

    assert answer == "推荐依据是 Python 经历。"
    messages = captured["messages"]
    assert len(messages) == 10  # system + 最近 8 条历史 + 本轮问题
    assert "history-0" not in [message.content for message in messages]
    assert "history-2" in [message.content for message in messages]
    assert "candidate-a.pdf" in messages[0].content
    assert '"match_score":82' in messages[0].content
    assert "Python 知识问答项目" in messages[0].content


def test_candidate_chat_explains_saved_score_with_llm_but_without_work_year_context(monkeypatch):
    captured = {}

    class FakeLlm:
        def invoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="规则分与语义分按保存的 70% / 30% 权重融合得到最终分。")

    monkeypatch.setattr(candidate_chat_mod, "_llm", FakeLlm())
    result = MatchResult(
        candidate_name="张三",
        match_score=69,
        matched_skills=["Python"],
        missing_skills=["PyTorch"],
        score_breakdown=ScoreBreakdown(
            skill_points=30,
            education_points=40,
            rule_score=70,
            llm_score=66,
            rule_weight=0.7,
            llm_weight=0.3,
            final_score=69,
            calibration_status="success",
        ),
        resume_text="张三，参与多模态问答项目。",
    )

    answer = answer_candidate_question(
        JDInfo(
            title="人工智能方向硕士研究生",
            skills=["Python", "PyTorch"],
            education_requirement="本科",
        ),
        result,
        [],
        "这个匹配分是怎么得出的？",
    )

    assert answer == "规则分与语义分按保存的 70% / 30% 权重融合得到最终分。"
    assert len(captured["messages"]) == 2
    system_prompt = captured["messages"][0].content
    assert '"rule_score":70' in system_prompt
    assert '"llm_score":66' in system_prompt
    assert '"rule_weight":0.7' in system_prompt
    assert '"llm_weight":0.3' in system_prompt
    assert "多模态问答项目" not in system_prompt
    assert "本轮只解释服务端保存的评分明细" in system_prompt


def test_candidate_chat_rejects_cross_candidate_comparison_without_calling_llm(monkeypatch):
    class FailingLlm:
        def invoke(self, _messages):
            raise AssertionError("跨候选人比较不应调用模型")

    monkeypatch.setattr(candidate_chat_mod, "_llm", FailingLlm())

    answer = answer_candidate_question(
        JDInfo(title="Python 工程师"),
        _match_result(),
        [],
        "这名候选人和其他候选人相比谁更适合？",
    )

    assert "只支持分析这名学生" in answer


def test_candidate_chat_endpoint_reads_candidate_from_owned_session(monkeypatch):
    import api.server as server_mod

    captured = {}
    authoritative = _match_result()

    def fake_snapshot(session_id, owner_user_id):
        captured["session"] = session_id
        captured["owner"] = owner_user_id
        return {
            "jd_info": JDInfo(title="Python 工程师"),
            "match_results": [authoritative],
        }

    def fake_answer(jd_info, match_result, history, message):
        captured["match_result"] = match_result
        captured["message"] = message
        return "可信回答"

    monkeypatch.setattr(server_mod, "get_session_snapshot", fake_snapshot)
    monkeypatch.setattr(server_mod, "answer_candidate_question", fake_answer)

    response = asyncio.run(
        server_mod.candidate_chat(
            CandidateChatRequest(
                session_id="session-a",
                resume_source="candidate-a.pdf",
                message="解释分数",
            ),
            _user={"sub": "73"},
        )
    )

    assert response.answer == "可信回答"
    assert captured["session"] == "session-a"
    assert captured["owner"] == 73
    assert captured["match_result"] is authoritative
    assert captured["message"] == "解释分数"


def test_candidate_chat_endpoint_rejects_candidate_outside_session(monkeypatch):
    import api.server as server_mod

    monkeypatch.setattr(
        server_mod,
        "get_session_snapshot",
        lambda _session_id, _owner_user_id: {
            "jd_info": JDInfo(title="Python 工程师"),
            "match_results": [_match_result("candidate-a.pdf")],
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            server_mod.candidate_chat(
                CandidateChatRequest(
                    session_id="session-a",
                    resume_source="candidate-b.pdf",
                    message="解释分数",
                ),
                _user={"sub": "73"},
            )
        )

    assert exc_info.value.status_code == 404
