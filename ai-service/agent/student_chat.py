"""Read-only, student-scoped question answering.

This deliberately uses one ordinary LLM call. It is not another Agent loop and
does not bind any tools, so a detail-drawer question cannot mutate matching state.
"""

import json
import logging
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.agent import _llm
from agent.prompt import STUDENT_CHAT_SYSTEM_PROMPT
from agent.schemas import StudentChatMessage, AdmissionCriteria, MatchResult
from agent.security import INJECTION_GUARD_SYSTEM, log_if_injection, wrap_untrusted
from config import SCORE_CALIBRATION_MAX_RESUME_CHARS

logger = logging.getLogger(__name__)

_CROSS_STUDENT_HINTS = (
    "其他学生",
    "别的学生",
    "另一个学生",
    "其余学生",
    "学生排名",
    "其他学生",
    "别的学生",
    "另一个学生",
    "其余学生",
    "这几位",
    "这几个人",
    "谁更适合",
    "谁更匹配",
    "学生排名",
)

_SCORE_EXPLANATION_HINTS = (
    "匹配分",
    "匹配度",
    "评分",
    "分数",
    "得分",
    "怎么得出",
    "如何计算",
    "怎么算",
)


def _response_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _is_cross_student_question(message: str) -> bool:
    normalized = (message or "").strip().lower()
    return any(hint.lower() in normalized for hint in _CROSS_STUDENT_HINTS)


def _is_score_explanation_question(message: str) -> bool:
    normalized = (message or "").strip().lower()
    return any(hint.lower() in normalized for hint in _SCORE_EXPLANATION_HINTS)


def answer_student_question(
    admission_criteria: AdmissionCriteria,
    match_result: MatchResult,
    history: list[StudentChatMessage],
    message: str,
) -> str:
    """Answer one question from authoritative, already-scored session data."""
    if _is_cross_student_question(message):
        return "当前详情抽屉只支持分析这名学生，暂不提供跨学生比较。你可以继续询问这名学生的匹配点、差距、风险、评分依据或面试核验重点。"

    is_score_explanation = _is_score_explanation_question(message)
    resume_text = match_result.resume_text[:SCORE_CALIBRATION_MAX_RESUME_CHARS]
    if not is_score_explanation:
        log_if_injection(resume_text, "student_chat")

    result_exclusions = {"resume_text"}
    if is_score_explanation:

        result_exclusions.update({"summary", "recommendation"})
    trusted_result = match_result.model_dump(exclude=result_exclusions)
    trusted_jd = admission_criteria.model_dump()
    resume_context = (
        "本轮只解释服务端保存的评分明细，不提供简历全文，也不重新评估学生。"
        if is_score_explanation
        else wrap_untrusted(resume_text, "resume")
    )
    system_prompt = INJECTION_GUARD_SYSTEM + "\n\n" + STUDENT_CHAT_SYSTEM_PROMPT.format(
        admission_criteria=wrap_untrusted(
            json.dumps(trusted_jd, ensure_ascii=False, separators=(",", ":")),
            "admission_criteria",
        ),
        match_result=json.dumps(trusted_result, ensure_ascii=False, separators=(",", ":")),
        resume_text=resume_context,
    )

    messages = [SystemMessage(content=system_prompt)]
    for item in history[-8:]:
        if item.role == "user":
            messages.append(HumanMessage(content=item.content))
        else:
            messages.append(AIMessage(content=item.content))
    messages.append(HumanMessage(content=message))

    started_at = time.monotonic()
    response = _llm.invoke(messages)
    logger.info(
        "llm_call=student_chat student=%s latency=%.1fms history_messages=%s",
        match_result.student_name,
        (time.monotonic() - started_at) * 1000,
        len(history[-8:]),
    )
    answer = _response_text(response.content)
    return answer or "暂时无法生成可靠回答，请换一种方式询问这名学生的匹配情况。"
