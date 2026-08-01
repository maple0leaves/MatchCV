"""State and schema definitions for the admission agent system."""

import re
from typing import Annotated, Literal, Optional
from typing_extensions import NotRequired, TypedDict
from pydantic import BaseModel, Field, field_validator, model_validator
from langgraph.graph.message import add_messages


_CJK_SUMMARY_MAX_CHARS = 220
_LATIN_SUMMARY_MAX_CHARS = 420
_SUMMARY_MAX_SENTENCES = 3


def _coerce_text_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return "；".join(str(item) for item in value.values() if item is not None)
    return str(value)


def compact_resume_summary(value) -> str:
    """Normalize and bound a resume summary without cutting a useful sentence early."""
    text = re.sub(r"\s+", " ", _coerce_text_value(value)).strip()
    if not text:
        return ""

    sentences = [
        item.strip()
        for item in re.split(r"(?<=[。！？])|(?<=[.!?])\s+", text)
        if item.strip()
    ]
    if len(sentences) > _SUMMARY_MAX_SENTENCES:
        text = "".join(sentences[:_SUMMARY_MAX_SENTENCES])

    max_chars = (
        _CJK_SUMMARY_MAX_CHARS
        if re.search(r"[\u4e00-\u9fff]", text)
        else _LATIN_SUMMARY_MAX_CHARS
    )
    if len(text) <= max_chars:
        return text

    candidate = text[:max_chars]
    boundary = max(candidate.rfind(mark) for mark in "。！？.!?；;")
    if boundary >= max_chars // 2:
        return candidate[: boundary + 1].rstrip()
    return candidate[: max_chars - 1].rstrip(" ，,；;：:") + "…"




class StudentProfile(BaseModel):
    """Structured student information extracted from a resume."""

    name: str = Field(default="", description="学生姓名")
    email: str = Field(default="", description="联系邮箱")
    skills: list[str] = Field(default_factory=list, description="技能列表")
    education: str = Field(default="", description="最高学历")
    summary: str = Field(default="", description="2-3 句话的简洁简历摘要")
    source: str = Field(default="", description="简历来源文件路径（用于去重，唯一标识一份简历）")

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skills(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,，、;；\n]", value) if item.strip()]
        return value

    @field_validator("education", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        return _coerce_text_value(value)

    @field_validator("summary", mode="before")
    @classmethod
    def _compact_summary(cls, value):
        return compact_resume_summary(value)

class ScoreBreakdown(BaseModel):
    """Stable scoring facts captured when the student is evaluated."""



    skill_points: float = Field(default=0, ge=0, le=100)
    education_points: float = Field(default=0, ge=0, le=100)
    rule_score: Optional[int] = Field(default=None, ge=0, le=100)
    llm_score: Optional[int] = Field(default=None, ge=0, le=100)
    rule_weight: float = Field(default=1, ge=0, le=1)
    llm_weight: float = Field(default=0, ge=0, le=1)
    final_score: int = Field(default=0, ge=0, le=100)
    calibration_status: Literal["success", "fallback", "disabled", "unavailable"] = "disabled"


class MatchResult(BaseModel):
    """Student-to-admission-criteria match evaluation result."""

    student_name: str = Field(default="", description="学生姓名")
    match_score: int = Field(default=0, ge=0, le=100, description="匹配分数 0-100")
    matched_skills: list[str] = Field(default_factory=list, description="匹配的技能")
    missing_skills: list[str] = Field(default_factory=list, description="缺失的技能")
    recommendation: str = Field(default="", description="推荐意见")
    should_proceed: bool = Field(default=False, description="是否建议推荐给导师面试")
    resume_source: str = Field(default="", description="简历来源文件路径（可选）")
    resume_text: str = Field(default="", description="简历全文（可选）")
    education: str = Field(default="", description="最高学历（从简历提取，供前端展示）")
    score_breakdown: ScoreBreakdown = Field(
        default_factory=ScoreBreakdown,
        description="匹配时保存的规则评分与 LLM 校准明细，供可信解释使用",
    )
    summary: str = Field(
        default="",
        description=(
            "学生简历摘要，供前端展示。优先是打分校准阶段 LLM 结合招收方向与"
            "期望条件生成的定向摘要；校准关闭/失败时退化为规则阶段的朴素文本摘要"
        ),
    )

    @model_validator(mode="after")
    def _backfill_legacy_score_breakdown(self):
        """Old checkpoints have only match_score; keep their explanation internally consistent."""
        breakdown = self.score_breakdown
        if (
            self.match_score > 0
            and breakdown.rule_score is None
            and breakdown.llm_score is None
            and breakdown.final_score == 0
        ):
            self.score_breakdown = breakdown.model_copy(update={
                "final_score": self.match_score,
                "calibration_status": "unavailable",
            })
        return self

    @field_validator("matched_skills", "missing_skills", mode="before")
    @classmethod
    def _coerce_skill_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,，、;；\n]", value) if item.strip()]
        return value

    @field_validator("recommendation", "resume_source", "resume_text", "summary", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        if value is None:
            return ""
        if isinstance(value, list):
            return "；".join(str(item) for item in value if item is not None)
        if isinstance(value, dict):
            return "；".join(str(item) for item in value.values() if item is not None)
        return str(value)

    @field_validator("match_score", mode="before")
    @classmethod
    def _coerce_score(cls, value):
        if value is None or value == "":
            return 0
        if isinstance(value, (int, float)):
            return max(0, min(100, int(value)))
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        return max(0, min(100, int(float(match.group(0))))) if match else 0

    @field_validator("should_proceed", mode="before")
    @classmethod
    def _coerce_bool(cls, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"true", "yes", "y", "1", "是", "建议", "推荐"}


class LLMScoreJudgment(BaseModel):
    """LLM 独立对学生与招收条件的匹配度打的一次语义分（0-100）。

    跟规则基线分按 SCORE_CALIBRATION_RULE_WEIGHT / SCORE_CALIBRATION_LLM_WEIGHT
    的权重加权求和得到最终分数（默认规则 70%、LLM 30%，见
    agent/agent.py::_llm_calibrate_score）。
    """

    score: int = Field(
        default=0, ge=0, le=100,
        description="LLM 独立给出的匹配分（0-100），按学生简历与招收条件的真实匹配程度打分，不参考规则基线分",
    )
    reasoning: str = Field(default="", description="打分理由，说明学生与招收条件匹配/不匹配的关键原因")
    resume_summary: str = Field(
        default="",
        description=(
            "结合本次招收方向和期望条件生成的学生简历摘要（2-3 句话，突出相关经历），"
            "复用本次打分调用而不单独加一次 LLM 请求"
        ),
    )

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_score(cls, value):
        if value is None or value == "":
            return 0
        if isinstance(value, (int, float)):
            return max(0, min(100, int(value)))
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        return max(0, min(100, int(float(match.group(0))))) if match else 0

    @field_validator("reasoning", "resume_summary", mode="before")
    @classmethod
    def _coerce_reasoning(cls, value):
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            items = value.values() if isinstance(value, dict) else value
            return "；".join(str(item) for item in items if item is not None)
        return str(value)




class AdmissionCriteria(BaseModel):
    """Structured admission criteria.

    描述导师招收硕士研究生时使用的方向与期望条件。
    """

    title: str = Field(default="", description="招收方向")
    skills: list[str] = Field(
        default_factory=list,
        description="具体技术、工具、框架、算法或研究方法；不包含经历、成果及英语数学水平",
    )
    education_requirement: str = Field(
        default="",
        description="申请硕士前学生当前具备的学历条件，默认本科",
    )
    description: str = Field(default="", description="完整期望条件")

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skill_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,，、;；\n]", value) if item.strip()]
        return value

    @field_validator("education_requirement", "description", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        if value is None:
            return ""
        if isinstance(value, list):
            return "；".join(str(item) for item in value if item is not None)
        if isinstance(value, dict):
            return "；".join(str(item) for item in value.values() if item is not None)
        return str(value)

class AdmissionCriteriaUpdateResult(BaseModel):
    """``update_admission_criteria`` 工具的结构化输出：合并反馈后的完整招收
    信息 + LLM 自己写的一句自然语言变更说明（供前端"调整结果"抽屉展示）。"""

    admission_criteria: AdmissionCriteria = Field(description="合并用户反馈后的完整招收信息")
    change_summary: str = Field(
        default="",
        description="一句话说明这次具体改了什么（如新增/移除了哪些技能、调整了哪个门槛）",
    )

    @field_validator("change_summary", mode="before")
    @classmethod
    def _coerce_summary(cls, value):
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            items = value.values() if isinstance(value, dict) else value
            return "；".join(str(item) for item in items if item is not None)
        return str(value)




class AgentState(TypedDict):
    """Full state for the single-agent ReAct workflow.

    只有 1 个 Agent（agent 节点）拥有任务级决策权；tools 节点只负责
    执行工具调用，自身不做决策。会话通过 session_id（= LangGraph
    thread_id）在多次 /api/admission/refine 调用间保持连续。
    """

    session_id: str
    owner_user_id: int
    match_top_k: NotRequired[int]

    admission_criteria: Optional[AdmissionCriteria]
    students: list[StudentProfile]
    match_results: list[MatchResult]






    last_search_result_json: NotRequired[str]



    completion_guard_retries: NotRequired[int]

    messages: Annotated[list, add_messages]




class AdmissionInput(BaseModel):
    """API request body."""

    user_input: str = Field(description="招生需求，例如：招收多模态大模型方向硕士研究生")
    top_k: int = Field(default=5, ge=1, le=30, description="智能匹配召回学生人数")

    @field_validator("user_input")
    @classmethod
    def _master_admission_only(cls, value):
        text = str(value or "").strip()
        title_match = re.search(r"(?:招收方向|招生方向)\s*[：:]\s*([^\n]+)", text)
        admission_title = title_match.group(1) if title_match else text.splitlines()[0] if text else ""
        if re.search(r"博士|硕博", admission_title):
            raise ValueError("当前仅支持硕士研究生申请筛选")
        return text


class AdmissionOutput(BaseModel):
    """API response body."""

    session_id: str = Field(description="会话 ID，追加反馈时需带上")
    match_results: list[MatchResult] = Field(default_factory=list, description="学生匹配结果列表")
    adjustment_note: Optional[str] = Field(
        default=None,
        description=(
            "仅当这一轮反馈触发了期望条件调整（update_admission_criteria）时才有值，"
            "说明具体改了什么，或在未完成重新检索打分时提示当前仍是调整前的结果。"
            "供前端「调整结果」抽屉展示，/api/admission 首次匹配恒为 None"
        ),
    )


class StudentChatMessage(BaseModel):
    """One bounded client-side conversation message."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


class StudentChatRequest(BaseModel):
    """Ask one read-only question about one student in a matching session."""

    session_id: str = Field(min_length=1, max_length=128)
    resume_source: str = Field(min_length=1, max_length=1000)
    message: str = Field(min_length=1, max_length=1000)
    history: list[StudentChatMessage] = Field(default_factory=list, max_length=8)

    @field_validator("session_id", "resume_source", "message")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class StudentChatResponse(BaseModel):
    answer: str
