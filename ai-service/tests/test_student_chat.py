"""Tests for student-scoped, read-only detail chat."""

import asyncio

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from pydantic import ValidationError

import agent.agent as agent_mod
import agent.student_chat as student_chat_mod
from agent.agent import _llm_calibrate_score, _local_match_score
from agent.student_chat import answer_student_question
from agent.schemas import (
    StudentChatMessage,
    StudentChatRequest,
    StudentProfile,
    AdmissionCriteria,
    LLMScoreJudgment,
    MatchResult,
    ScoreBreakdown,
)


def _match_result(source: str = "student-a.pdf") -> MatchResult:
    return MatchResult(
        student_name="张三",
        match_score=82,
        matched_skills=["Python"],
        missing_skills=["Kubernetes"],
        recommendation="Python 项目经验与方向相关",
        resume_source=source,
        resume_text="张三，使用 Python 参与知识问答系统建设。",
        education="本科",
        summary="参与 Python 知识问答项目。",
    )


def test_local_score_records_reusable_score_breakdown():
    result = _local_match_score(
        StudentProfile(
            name="张三",
            skills=["Python"],
            education="本科",
        ),
        AdmissionCriteria(
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
    result = MatchResult(student_name="旧会话学生", match_score=82)

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
        MatchResult(student_name="张三", match_score=60),
        admission_criteria=None,
        resume_text="Python",
    )

    assert result.match_score == 69
    assert result.score_breakdown.rule_score == 60
    assert result.score_breakdown.llm_score == 90
    assert result.score_breakdown.rule_weight == 0.7
    assert result.score_breakdown.llm_weight == 0.3
    assert result.score_breakdown.final_score == 69
    assert result.score_breakdown.calibration_status == "success"


def test_student_chat_request_rejects_more_than_eight_history_messages():
    history = [
        {"role": "user", "content": f"问题 {index}"}
        for index in range(9)
    ]

    with pytest.raises(ValidationError):
        StudentChatRequest(
            session_id="session-a",
            resume_source="student-a.pdf",
            message="为什么推荐？",
            history=history,
        )


def test_student_chat_uses_bounded_history_and_authoritative_context(monkeypatch):
    captured = {}

    class FakeLlm:
        def invoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="推荐依据是 Python 经历。")

    monkeypatch.setattr(student_chat_mod, "_llm", FakeLlm())
    history = [
        StudentChatMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"history-{index}",
        )
        for index in range(10)
    ]

    answer = answer_student_question(
        AdmissionCriteria(title="具备 Python 基础的硕士生", skills=["Python", "Kubernetes"]),
        _match_result(),
        history,
        "为什么推荐？",
    )

    assert answer == "推荐依据是 Python 经历。"
    messages = captured["messages"]
    assert len(messages) == 10
    assert "history-0" not in [message.content for message in messages]
    assert "history-2" in [message.content for message in messages]
    assert "student-a.pdf" in messages[0].content
    assert '"match_score":82' in messages[0].content
    assert "Python 知识问答项目" in messages[0].content


def test_student_chat_explains_saved_score_with_llm_but_without_work_year_context(monkeypatch):
    captured = {}

    class FakeLlm:
        def invoke(self, messages):
            captured["messages"] = messages
            return AIMessage(content="规则分与语义分按保存的 70% / 30% 权重融合得到最终分。")

    monkeypatch.setattr(student_chat_mod, "_llm", FakeLlm())
    result = MatchResult(
        student_name="张三",
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

    answer = answer_student_question(
        AdmissionCriteria(
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


def test_student_chat_rejects_cross_student_comparison_without_calling_llm(monkeypatch):
    class FailingLlm:
        def invoke(self, _messages):
            raise AssertionError("跨学生比较不应调用模型")

    monkeypatch.setattr(student_chat_mod, "_llm", FailingLlm())

    answer = answer_student_question(
        AdmissionCriteria(title="具备 Python 基础的硕士生"),
        _match_result(),
        [],
        "这名学生和其他学生相比谁更适合？",
    )

    assert "只支持分析这名学生" in answer


def test_student_chat_endpoint_reads_student_from_owned_session(monkeypatch):
    import api.server as server_mod

    captured = {}
    authoritative = _match_result()

    def fake_snapshot(session_id, owner_user_id):
        captured["session"] = session_id
        captured["owner"] = owner_user_id
        return {
            "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生"),
            "match_results": [authoritative],
        }

    def fake_answer(admission_criteria, match_result, history, message):
        captured["match_result"] = match_result
        captured["message"] = message
        return "可信回答"

    monkeypatch.setattr(server_mod, "get_session_snapshot", fake_snapshot)
    monkeypatch.setattr(server_mod, "answer_student_question", fake_answer)

    response = asyncio.run(
        server_mod.student_chat(
            StudentChatRequest(
                session_id="session-a",
                resume_source="student-a.pdf",
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


def test_student_chat_endpoint_rejects_student_outside_session(monkeypatch):
    import api.server as server_mod

    monkeypatch.setattr(
        server_mod,
        "get_session_snapshot",
        lambda _session_id, _owner_user_id: {
            "admission_criteria": AdmissionCriteria(title="具备 Python 基础的硕士生"),
            "match_results": [_match_result("student-a.pdf")],
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            server_mod.student_chat(
                StudentChatRequest(
                    session_id="session-a",
                    resume_source="student-b.pdf",
                    message="解释分数",
                ),
                _user={"sub": "73"},
            )
        )

    assert exc_info.value.status_code == 404
