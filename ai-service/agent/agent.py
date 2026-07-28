"""Single-agent ReAct implementation: the decision-making agent node,
its tool executor, and the deterministic scoring helpers they both rely on.
"""

import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from typing import Literal

from config import (
    LLM_DISABLE_THINKING,
    LLM_FALLBACK_API_KEY,
    LLM_FALLBACK_BASE_URL,
    LLM_FALLBACK_MODEL,
    LLM_FALLBACK_STRUCTURED_METHOD,
    LLM_FORCE_FALLBACK,
    LLM_MODEL,
    LLM_STRUCTURED_METHOD,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    RAG_TOP_K,
    SCORE_CALIBRATION_ENABLED,
    SCORE_CALIBRATION_LLM_WEIGHT,
    SCORE_CALIBRATION_MAX_RESUME_CHARS,
    SCORE_CALIBRATION_RULE_WEIGHT,
)



_THINKING_EXTRA_BODY = {"enable_thinking": False} if LLM_DISABLE_THINKING else None
from agent.observability import log_tool_usage, trace_agent_step
from agent.security import INJECTION_GUARD_SYSTEM, log_if_injection, wrap_untrusted
from agent.schemas import (
    AgentState,
    StudentProfile,
    AdmissionCriteria,
    AdmissionCriteriaUpdateResult,
    LLMScoreJudgment,
    MatchResult,
    ScoreBreakdown,
)
from agent.tools import ALL_TOOLS, TOOLS_BY_NAME
from agent.prompt import (
    AGENT_SYSTEM_PROMPT,
    COMPLETION_GUARD_REPAIR_PROMPT,
    ADMISSION_CRITERIA_PARSE_PROMPT,
    ADMISSION_CRITERIA_UPDATE_PROMPT,
    SCORE_CALIBRATION_PROMPT,
)

logger = logging.getLogger(__name__)



_CONTEXT_KEEP_ROUNDS = 3
_CONTEXT_TEXT_LIMIT = 200
_CONTEXT_SKILL_LIMIT = 8


_COMPLETION_GUARD_MAX_RETRIES = 2


class SearchResultValidationError(ValueError):
    """Raised when search_students returns data that cannot be scored safely."""


class AgentWorkflowIncompleteError(RuntimeError):
    """Raised when the Agent still ends after exhausting bounded workflow repairs."""


def _build_llm(temperature: float = LLM_TEMPERATURE):
    """Build LLM instance with an optional OpenAI-compatible fallback."""
    fallback = _build_fallback_llm(temperature)
    if LLM_FORCE_FALLBACK and fallback:
        return fallback
    primary = _build_primary_llm(temperature)
    return primary.with_fallbacks([fallback]) if fallback else primary


def _build_primary_llm(temperature: float = LLM_TEMPERATURE):
    """Build the primary LLM instance, supporting OpenAI-compatible gateways."""
    if OPENAI_BASE_URL:
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            timeout=LLM_TIMEOUT,
            default_headers={"HTTP-Referer": "https://github.com/admission-agent"},
            extra_body=_THINKING_EXTRA_BODY,
        )
    return init_chat_model(f"openai:{LLM_MODEL}", temperature=temperature)


def _build_fallback_llm(temperature: float = LLM_TEMPERATURE):
    """Build the optional fallback LLM. Returns None when not configured."""
    if not (LLM_FALLBACK_API_KEY and LLM_FALLBACK_BASE_URL and LLM_FALLBACK_MODEL):
        return None
    return ChatOpenAI(
        model=LLM_FALLBACK_MODEL,
        temperature=temperature,
        api_key=LLM_FALLBACK_API_KEY,
        base_url=LLM_FALLBACK_BASE_URL,
        timeout=LLM_TIMEOUT,
        default_headers={"HTTP-Referer": "https://github.com/admission-agent"},
        extra_body=_THINKING_EXTRA_BODY,
    )


def _build_structured_llm(schema, temperature: float = LLM_TEMPERATURE):
    """Build a structured-output LLM with fallback support.

    DeepSeek v4 flash currently rejects tool/function structured output but
    accepts JSON mode, so fallback structured calls use a configurable method.
    """
    fallback = _build_fallback_llm(temperature)
    if LLM_FORCE_FALLBACK and fallback:
        return fallback.with_structured_output(
            schema,
            method=LLM_FALLBACK_STRUCTURED_METHOD,
        )
    primary = _build_primary_llm(temperature).with_structured_output(
        schema,
        method=LLM_STRUCTURED_METHOD,
    )
    if not fallback:
        return primary
    return primary.with_fallbacks([
        fallback.with_structured_output(
            schema,
            method=LLM_FALLBACK_STRUCTURED_METHOD,
        )
    ])


_llm = _build_llm()
_admission_criteria_llm = _build_structured_llm(AdmissionCriteria)
_admission_criteria_update_llm = _build_structured_llm(AdmissionCriteriaUpdateResult)
_llm_with_tools = _llm.bind_tools(ALL_TOOLS, tool_choice="auto")


def _state_top_k(state: AgentState) -> int:
    """Read and clamp the requested student recall count from graph state."""
    try:
        value = int(state.get("match_top_k") or RAG_TOP_K)
    except (TypeError, ValueError):
        value = RAG_TOP_K
    return max(1, min(30, value))


def _student_key(student: StudentProfile) -> str:
    """Create a stable key for student deduplication.

    优先用简历文件路径（唯一，一份简历对应一个文件），其次邮箱，最后才退化到
    姓名——姓名不保证唯一（重名很常见），单独用姓名做 key 会导致同名学生
    在 student_map 里互相覆盖、静默丢数据。
    """
    return student.source or student.email or student.name


def _coerce_student(value: StudentProfile | dict | str) -> StudentProfile:
    """Convert tool outputs into StudentProfile."""
    if isinstance(value, StudentProfile):
        return value
    if isinstance(value, str):
        return StudentProfile.model_validate_json(value)
    return StudentProfile.model_validate(value)


def _dedupe_display_name(name: str, taken_names: set[str]) -> str:
    """给重名学生追加区分后缀，避免 match_map 用姓名做 key 时互相覆盖。

    学生姓名不保证唯一（同姓同名在真实简历库里并不罕见），但姓名同时也是
    match_map 的 key、也是最终报告里 Agent 唯一能引用学生的方式。必须在
    学生第一次写入 match_map 时就去重——事后再处理时，前一个同名学生的
    数据已经被覆盖、不可恢复。
    """
    base = (name or "未知学生").strip() or "未知学生"
    if base not in taken_names:
        return base
    suffix = 2
    while f"{base}（{suffix}）" in taken_names:
        suffix += 1
    return f"{base}（{suffix}）"


def _coerce_match_result(value: MatchResult | dict | str) -> MatchResult:
    """Convert tool outputs into MatchResult."""
    if isinstance(value, MatchResult):
        return value
    if isinstance(value, str):
        return MatchResult.model_validate_json(value)
    return MatchResult.model_validate(value)


def _validate_search_result(raw_result: str) -> tuple[str, int]:
    """Validate and normalize the private search payload stored in Agent State.

    Student-controlled text must never be copied into the decision Agent's
    ToolMessage. This helper validates the private payload first; the caller stores the
    normalized JSON in ``last_search_result_json`` and emits only a fixed observation.
    """
    try:
        payload = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SearchResultValidationError(
            "search_students returned invalid JSON"
        ) from exc
    if not isinstance(payload, list):
        raise SearchResultValidationError(
            "search_students result must be a JSON array"
        )

    normalized_students = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SearchResultValidationError(
                f"search_students item {index} must be an object"
            )
        normalized = dict(item)
        for field in ("name", "email", "source", "content"):
            if field in normalized:
                value = normalized[field]
                normalized[field] = "" if value is None else str(value)
        if (
            not normalized.get("source", "").strip()
            and not normalized.get("content", "").strip()
        ):
            raise SearchResultValidationError(
                f"search_students item {index} has no resume source or content"
            )
        normalized_students.append(normalized)

    return (
        json.dumps(normalized_students, ensure_ascii=False),
        len(normalized_students),
    )


_NON_RULE_SKILL_MARKERS = (
    "科研经历",
    "研究经历",
    "项目经历",
    "项目经验",
    "实习经历",
    "科研与项目经历",
    "课程设计",
    "论文",
    "竞赛",
    "比赛",
    "开源项目",
    "实验成果",
    "科研成果",
    "研究成果",
    "学术成果",
    "专业背景",
    "课程成绩",
)
_CURRENT_EDUCATION_RE = re.compile(
    r"(?:当前|现有|已获|最高)?\s*学历(?:条件|要求)?\s*"
    r"(?:为|是|需(?:要)?|至少(?:达到)?|最低(?:为)?)?\s*[：:]?\s*"
    r"(专科|大专|本科|硕士|研究生|博士)"
)


def _is_non_rule_skill(value: str) -> bool:
    """Return whether a parsed item belongs in semantic criteria, not skill rules."""
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return True
    if any(marker in compact for marker in _NON_RULE_SKILL_MARKERS):
        return True
    if compact.startswith(("英语", "英文")):
        return True
    if re.fullmatch(r"数学(?:成绩|优秀|良好|较好|高|基础(?:扎实)?|扎实)?", compact):
        return True
    return False


def _normalize_master_admission_criteria(admission_criteria: AdmissionCriteria, source_text: str = "") -> AdmissionCriteria:
    """Normalize parsed criteria for the master-admission-only product scope.

    ``title`` describes the degree being applied for, while
    ``education_requirement`` describes the applicant's current attained level.
    For master's admission the default current level is therefore bachelor's.
    Qualitative evidence and achievements stay in ``description`` for the LLM
    instead of becoming brittle exact-match skill rules.
    """
    normalized_skills: list[str] = []
    seen: set[str] = set()
    for raw_skill in admission_criteria.skills:
        skill = str(raw_skill).strip()
        key = skill.casefold()
        if not skill or key in seen or _is_non_rule_skill(skill):
            continue
        normalized_skills.append(skill)
        seen.add(key)

    explicit_current_education = _CURRENT_EDUCATION_RE.search(source_text or "")
    education_requirement = (admission_criteria.education_requirement or "").strip()
    if explicit_current_education:
        education_requirement = explicit_current_education.group(1)
    elif not education_requirement or any(
        target in education_requirement for target in ("硕士", "研究生", "博士")
    ):
        education_requirement = "本科"

    return admission_criteria.model_copy(update={
        "skills": normalized_skills,
        "education_requirement": education_requirement,
    })


def _parse_admission_criteria(user_input: str) -> AdmissionCriteria:
    """Parse and normalize master's admission criteria from user input."""
    parsed = _admission_criteria_llm.invoke(ADMISSION_CRITERIA_PARSE_PROMPT.format(user_input=user_input))
    return _normalize_master_admission_criteria(parsed, user_input)


def _update_admission_criteria(old_admission_criteria: AdmissionCriteria, feedback_text: str) -> AdmissionCriteriaUpdateResult:
    """用用户反馈增量合并已解析的招收信息（支持新增/修改/删除字段），LLM 同时
    给出一句自然语言变更说明，供 update_admission_criteria 工具、API 层的
    "调整说明"展示复用。任何异常都回退到原招收信息、不改变量，不让单次 LLM
    调用失败中断整个反馈流程（与 _llm_calibrate_score 的兜底风格一致）。
    """
    prompt = ADMISSION_CRITERIA_UPDATE_PROMPT.format(
        admission_criteria=old_admission_criteria.model_dump_json(ensure_ascii=False),
        feedback_text=feedback_text or "",
    )
    try:
        updated = _admission_criteria_update_llm.invoke(prompt)
        return updated.model_copy(update={
            "admission_criteria": _normalize_master_admission_criteria(updated.admission_criteria, feedback_text),
        })
    except Exception as exc:
        logger.warning("招收信息更新失败，保留原招收信息: %s", exc)
        return AdmissionCriteriaUpdateResult(admission_criteria=old_admission_criteria, change_summary="")


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")



_STUDENT_PARALLELISM = int(os.getenv("STUDENT_PARALLELISM", "8"))


def _process_one_student(
    student_payload: dict,
    admission_criteria: AdmissionCriteria | None,
) -> tuple[StudentProfile, MatchResult] | None:
    """Build a student profile and score it against the admission criteria.

    先用确定性规则（技能 60%、学历 40%，按用户实际填写的维度归一化）算出
    基线分，再交给 ``_llm_calibrate_score`` 独立评估研究方向、科研项目、
    技术方法和学术成果。两个分数按配置权重融合，默认规则 70%、LLM 30%。

    简历全文获取优先级：
    1. payload 自带 ``resume_text``（向后兼容旧数据 / 直接传入的场景）
    2. 通过 ``source`` 路径调 ``_read_resume_file``（带 LRU 缓存，零额外成本）
    3. 退化使用 ``content`` 摘要（短文本兜底）
    """
    resume_text = student_payload.get("resume_text") or ""
    source = student_payload.get("source", "")
    if not resume_text and source:
        try:
            from agent.tools import _read_resume_file

            resume_text = _read_resume_file(source)
        except Exception as exc:
            print(f"⚠️ 读取简历失败 {source}: {exc}")
    if not resume_text:
        resume_text = student_payload.get("content", "")
    if not resume_text:
        return None

    student = _local_student_profile(student_payload, resume_text, admission_criteria)
    match_result = _local_match_score(student, admission_criteria, resume_text)
    match_result = _llm_calibrate_score(match_result, admission_criteria, resume_text)
    match_result.resume_source = student_payload.get("source", "")
    match_result.resume_text = resume_text
    return student, match_result



_LLM_SCORE_CALIBRATOR = None


def _get_score_calibrator():
    """Return a process-wide singleton LLM bound to LLMScoreJudgment schema."""
    global _LLM_SCORE_CALIBRATOR
    if _LLM_SCORE_CALIBRATOR is None:
        _LLM_SCORE_CALIBRATOR = _build_structured_llm(LLMScoreJudgment)
    return _LLM_SCORE_CALIBRATOR


def _llm_calibrate_score(base: MatchResult, admission_criteria: AdmissionCriteria | None, resume_text: str) -> MatchResult:
    """规则基线分 + LLM 独立语义分，按权重加权融合得到最终分数。

    这是"规则打底、LLM 只能 ±固定分微调"两段式设计的升级版：LLM 不再是在规则
    基线分上打补丁，而是完全独立地对学生与招收条件的匹配度打一次 0-100 分，跟
    规则基线分各占 SCORE_CALIBRATION_RULE_WEIGHT / SCORE_CALIBRATION_LLM_WEIGHT
    （默认规则 70%、LLM 30%）的权重加权求和——这样既能利用语义判断补足规则
    难以覆盖的维度，也能限制模型采样波动对最终排序的影响。任何异常都完全回退
    到规则基线分（相当于
    规则权重 = 100%），保证批量匹配流程不因单个 LLM 调用失败而中断。

    简历全文按 SCORE_CALIBRATION_MAX_RESUME_CHARS 截断（默认 5000 字）。这里
    评估过 Map-Reduce 分块摘要方案，但实测 1 页中文简历提取出的文本约
    1400~1600 字，2 页简历基本落在 3000 字上下——分块摘要在这个量级上收益
    有限（切出来往往就 1~2 块），却引入切块/并行调用/失败兜底的复杂度；而
    现有 LLM 的上下文窗口（64k~128k tokens）本来就装得下更长的原文，直接
    放宽截断上限、单次调用喂全文，比"切块摘要"更简单也更准确（摘要有损，
    原文无损）。
    """
    rule_score = base.score_breakdown.rule_score or base.match_score
    if not SCORE_CALIBRATION_ENABLED:
        base.score_breakdown = base.score_breakdown.model_copy(update={
            "rule_score": rule_score,
            "llm_score": None,
            "rule_weight": 1,
            "llm_weight": 0,
            "final_score": base.match_score,
            "calibration_status": "disabled",
        })
        return base

    total_weight = SCORE_CALIBRATION_RULE_WEIGHT + SCORE_CALIBRATION_LLM_WEIGHT
    if total_weight <= 0 or SCORE_CALIBRATION_LLM_WEIGHT <= 0:
        base.score_breakdown = base.score_breakdown.model_copy(update={
            "rule_score": rule_score,
            "llm_score": None,
            "rule_weight": 1,
            "llm_weight": 0,
            "final_score": base.match_score,
            "calibration_status": "disabled",
        })
        return base

    log_if_injection(resume_text, "score_calibration")
    t0 = time.monotonic()
    try:
        prompt = INJECTION_GUARD_SYSTEM + "\n\n" + SCORE_CALIBRATION_PROMPT.format(
            admission_criteria=wrap_untrusted(admission_criteria.model_dump_json(), "admission_criteria") if admission_criteria else "{}",
            matched_skills=", ".join(base.matched_skills) or "无",
            missing_skills=", ".join(base.missing_skills) or "无",
            resume_text=wrap_untrusted(resume_text[:SCORE_CALIBRATION_MAX_RESUME_CHARS], "resume"),
        )
        judgment = _get_score_calibrator().invoke(prompt)
    except Exception as exc:
        logger.warning(
            "llm_call=score_calibration student=%s latency=%.1fms failed: %s",
            base.student_name, (time.monotonic() - t0) * 1000, exc,
        )
        print(f"⚠️ LLM 打分失败，回退规则分：{exc}")
        base.score_breakdown = base.score_breakdown.model_copy(update={
            "rule_score": rule_score,
            "llm_score": None,
            "rule_weight": 1,
            "llm_weight": 0,
            "final_score": base.match_score,
            "calibration_status": "fallback",
        })
        return base
    logger.info(
        "llm_call=score_calibration student=%s latency=%.1fms",
        base.student_name, (time.monotonic() - t0) * 1000,
    )

    ai_summary = (judgment.resume_summary or "").strip()
    if ai_summary:
        base.summary = ai_summary





    reason = (judgment.reasoning or "").strip()
    if reason:
        base.recommendation = reason

    rule_weight = SCORE_CALIBRATION_RULE_WEIGHT / total_weight
    llm_weight = SCORE_CALIBRATION_LLM_WEIGHT / total_weight
    blended_score = rule_score * rule_weight + judgment.score * llm_weight
    new_score = max(0, min(100, int(round(blended_score))))
    base.match_score = new_score
    base.should_proceed = new_score >= _PROCEED_THRESHOLD
    base.score_breakdown = base.score_breakdown.model_copy(update={
        "rule_score": rule_score,
        "llm_score": judgment.score,
        "rule_weight": round(rule_weight, 4),
        "llm_weight": round(llm_weight, 4),
        "final_score": new_score,
        "calibration_status": "success",
    })
    return base


_COMMON_SKILLS = [
    "Java", "Python", "Spring Boot", "Spring Cloud", "FastAPI", "Django", "Flask",
    "React", "Vue", "Next.js", "TypeScript", "JavaScript", "Node.js", "NestJS",
    "SQL", "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch",
    "Docker", "Kubernetes", "Linux", "Git", "CI/CD", "RESTful API", "微服务",
    "单元测试", "性能优化", "Kafka", "Flink", "Spark", "LangChain", "Milvus",
    "pgvector", "RAG", "Figma", "Axure", "CRM", "数据分析", "项目管理", "产品设计",
]


def _looks_like_hash_name(value: str) -> bool:
    compact = re.sub(r"[^0-9a-fA-F]", "", value or "")
    return len(compact) >= 24 and len(compact) >= len((value or "").replace(" ", "")) * 0.8


def _looks_like_pinyin_name(value: str) -> bool:
    value = (value or "").strip()
    if not value or re.search(r"[\u4e00-\u9fff]", value):
        return False
    return bool(re.fullmatch(r"[A-Za-z]+(?:[ _-][A-Za-z]+){1,3}", value))


def _guess_name_from_resume(resume_text: str, fallback: str) -> str:
    fallback = (fallback or "").strip()
    first_reasonable = ""
    for line in resume_text.splitlines()[:8]:
        cleaned = line.strip().strip("|｜,，;；")
        if not cleaned:
            continue
        cleaned = re.sub(r"^(姓名|Name|name)[:：]\s*", "", cleaned).strip()
        cleaned = re.split(r"\s+[0-9]{3,}|\s*\|\s*|[，,]\s*", cleaned)[0].strip()
        if _EMAIL_RE.search(cleaned):
            continue
        if not first_reasonable and 1 < len(cleaned) <= 32:
            first_reasonable = cleaned
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", cleaned):
            return cleaned

    if fallback and not _looks_like_hash_name(fallback) and not _looks_like_pinyin_name(fallback):
        return fallback
    if first_reasonable and not _looks_like_hash_name(first_reasonable):
        return first_reasonable
    if fallback and not _looks_like_hash_name(fallback):
        return fallback
    return "未知学生"


_CHINESE_EDUCATION_TARGET = (
    r"(?:博士研究生|硕士研究生|博士|硕士|研究生|本科)"
    r"(?:\s*[/／、或和]\s*(?:博士研究生|硕士研究生|博士|硕士|研究生|本科))*"
)
_EDUCATION_INTENT_PATTERNS = (
    re.compile(
        rf"(?:计划|拟|希望|准备|意向|目标|有意)?\s*"
        rf"(?:申请|报考|申报|报名|招收|招生|要求|期望)"
        rf"[^。\n；;]{{0,60}}?{_CHINESE_EDUCATION_TARGET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_CHINESE_EDUCATION_TARGET}"
        rf"\s*(?:项目|学位)?\s*(?:申请|报考)(?:示例|意向)?(?:简历)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:plan(?:ning)?\s+to|intend(?:ing)?\s+to|seek(?:ing)?\s+to)?\s*"
        r"(?:apply(?:ing)?|application)\s+(?:to|for)?"
        r"[^.\n;]{0,80}?"
        r"(?:ph\.?\s*d\.?|doctor(?:ate|al)?|master(?:'s)?|m\.?\s*sc\.?|"
        r"m\.?\s*s\.?|bachelor(?:'s)?|b\.?\s*sc\.?|b\.?\s*s\.?)",
        re.IGNORECASE,
    ),
)


def _without_education_intent(text: str) -> str:
    """Remove admission targets so they cannot be mistaken for attained education."""
    cleaned = text
    for pattern in _EDUCATION_INTENT_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


def _extract_education(text: str) -> str:
    cleaned = _without_education_intent(text)


    explicit_patterns = (
        (
            "博士",
            (
                r"博士(?:研究生)?(?:在读|毕业|学历|学位|阶段|学生)",
                r"(?:获|获得|取得|攻读|就读)[^。\n；;]{0,20}博士",
                r"\bph\.?\s*d\.?\b",
                r"\bdoctoral\s+(?:student|student|degree)\b",
                r"\bdoctorate\b",
            ),
        ),
        (
            "硕士",
            (
                r"硕士(?:研究生)?(?:在读|毕业|学历|学位|阶段)",
                r"研究生(?:在读|毕业|学历|学位|阶段)",
                r"(?:获|获得|取得|攻读|就读)[^。\n；;]{0,20}(?:硕士|研究生)",
                r"\bm\.?\s*sc\.?\b",
                r"\bm\.?\s*s\.?\b",
                r"\bmaster(?:'s)?\s+degree\b",
            ),
        ),
        (
            "本科",
            (
                r"本科(?:在读|毕业|学历|阶段|生)",
                r"(?:工学|理学|文学|管理学|经济学|法学|教育学|医学|农学|艺术学)?学士(?:学位)?",
                r"(?:获|获得|取得|攻读|就读)[^。\n；;]{0,20}(?:本科|学士)",
                r"\bb\.?\s*sc\.?\b",
                r"\bb\.?\s*s\.?\b",
                r"\bbachelor(?:'s)?\s+degree\b",
            ),
        ),
        ("专科", (r"(?:大专|专科)(?:在读|毕业|学历|阶段|生)",)),
    )
    for level, patterns in explicit_patterns:
        if any(re.search(pattern, cleaned, re.IGNORECASE) for pattern in patterns):
            return level

    for value in ["博士", "硕士", "研究生", "本科", "大专", "专科"]:
        if value in cleaned:
            return value
    lowered = cleaned.lower()
    if "master" in lowered or "msc" in lowered:
        return "硕士"
    if "bachelor" in lowered or "bsc" in lowered:
        return "本科"
    return ""


def _skill_in_text(skill: str, text_lower: str) -> bool:
    lowered = skill.lower().strip()
    if not lowered:
        return False
    variants = {lowered, lowered.replace(" ", ""), lowered.replace(".", "")}
    normalized_text = text_lower.replace(" ", "")
    return any(variant in text_lower or variant in normalized_text for variant in variants)


def _extract_student_skills(resume_text: str, admission_criteria: AdmissionCriteria | None) -> list[str]:
    text_lower = resume_text.lower()
    skill_pool: list[str] = []
    if admission_criteria:
        skill_pool.extend(admission_criteria.skills or [])
    skill_pool.extend(_COMMON_SKILLS)

    skills: list[str] = []
    seen: set[str] = set()
    for skill in skill_pool:
        normalized = skill.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        if _skill_in_text(normalized, text_lower):
            skills.append(normalized)
            seen.add(key)
    return skills


def _local_student_profile(student_payload: dict, resume_text: str, admission_criteria: AdmissionCriteria | None) -> StudentProfile:
    fallback_name = student_payload.get("name", "") or _derive_name_from_source(student_payload.get("source", ""))
    email = student_payload.get("email", "")
    if not email:
        match = _EMAIL_RE.search(resume_text)
        email = match.group(0) if match else ""

    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    return StudentProfile(
        name=_guess_name_from_resume(resume_text, fallback_name),
        email=email,
        skills=_extract_student_skills(resume_text, admission_criteria),
        education=_extract_education(resume_text),
        summary=" ".join(lines[:8])[:800],
        source=student_payload.get("source", ""),
    )





_SKILL_WEIGHT = 60
_EDUCATION_WEIGHT = 40
_PROCEED_THRESHOLD = 60
_SKILL_UNKNOWN_RATIO = 0.7


def _education_score(student_education: str, requirement: str) -> float:
    """学历匹配因子 [0,1]：达到/超过要求或无要求为 1.0，否则 0.0。"""
    if not requirement:
        return 1.0
    rank = {"专科": 1, "大专": 1, "本科": 2, "研究生": 3, "硕士": 3, "博士": 4}
    required = max((rank[key] for key in rank if key in requirement), default=0)
    student = max((rank[key] for key in rank if key in student_education), default=0)
    if not required:
        return 1.0
    return 1.0 if student >= required else 0.0


def _local_match_score(student: StudentProfile, admission_criteria: AdmissionCriteria | None, resume_text: str) -> MatchResult:
    text_lower = (resume_text + "\n" + " ".join(student.skills)).lower()

    skills_required = [skill.strip() for skill in (admission_criteria.skills if admission_criteria else []) if skill.strip()]
    education_requirement = (admission_criteria.education_requirement if admission_criteria else "").strip()

    matched = [skill for skill in skills_required if _skill_in_text(skill, text_lower)]
    missing = [skill for skill in skills_required if skill not in matched]
    skill_ratio = len(matched) / len(skills_required) if skills_required else _SKILL_UNKNOWN_RATIO




    has_skills = bool(skills_required)
    has_education = bool(education_requirement)
    if has_skills and has_education:
        skill_budget = float(_SKILL_WEIGHT)
        education_budget = float(_EDUCATION_WEIGHT)
    elif has_skills:
        skill_budget = 100.0
        education_budget = 0.0
    elif has_education:
        skill_budget = 0.0
        education_budget = 100.0
    else:
        skill_budget = 100.0
        education_budget = 0.0

    skill_points = skill_ratio * skill_budget
    education_points = (
        _education_score(student.education, education_requirement)
        * education_budget
    )

    score = int(round(skill_points + education_points))
    score = max(0, min(100, score))





    recommendation = (
        "学生的技能与学历基本符合期望条件，建议推荐给导师面试进一步评估"
        if score >= _PROCEED_THRESHOLD
        else "学生在核心技能或学历条件上存在差距，建议进一步复核"
    )

    return MatchResult(
        student_name=student.name,
        match_score=score,
        matched_skills=matched,
        missing_skills=missing,
        recommendation=recommendation,
        should_proceed=score >= _PROCEED_THRESHOLD,
        education=student.education,
        score_breakdown=ScoreBreakdown(
            skill_points=round(skill_points, 2),
            education_points=round(education_points, 2),
            rule_score=score,
            final_score=score,
        ),
        summary=student.summary,
    )


def _derive_name_from_source(source: str) -> str:
    """Best-effort name fallback derived from the resume file name."""
    if not source:
        return ""
    stem = os.path.splitext(os.path.basename(source))[0]
    return stem.replace("_", " ").title()


def _select_recent_rounds(messages: list, keep_rounds: int = _CONTEXT_KEEP_ROUNDS) -> list:
    """Return the newest complete HumanMessage-delimited rounds.

    Tool calls and their ToolMessages must be kept as one unit. Cutting by a raw message
    count can leave an orphaned tool call/response pair and make OpenAI-compatible APIs
    reject the request, so the window boundary is always a HumanMessage.
    """
    if keep_rounds < 1:
        raise ValueError("keep_rounds must be at least 1")
    round_starts = [
        index for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
    ]
    if len(round_starts) <= keep_rounds:
        return list(messages)
    return list(messages[round_starts[-keep_rounds]:])


def _bounded_context_text(value: str) -> str:
    """Keep state snapshots compact and deterministic."""
    text = (value or "").strip()
    if len(text) <= _CONTEXT_TEXT_LIMIT:
        return text
    return text[:_CONTEXT_TEXT_LIMIT] + "…"


def _build_match_results_context(state: AgentState) -> str:
    """Serialize the authoritative current match state for the Agent system prompt.

    Once old dialogue rounds slide out of ``messages``, the Agent must not rely on an
    old score_students_batch ToolMessage to remember current students. The compact
    snapshot below is derived from the structured State, so it cannot drift away from
    the data returned to the API.
    """
    compact_results = []
    for value in state.get("match_results", []):
        result = _coerce_match_result(value)
        compact_results.append({
            "student_name": result.student_name,
            "match_score": result.match_score,
            "matched_skills": result.matched_skills[:_CONTEXT_SKILL_LIMIT],
            "missing_skills": result.missing_skills[:_CONTEXT_SKILL_LIMIT],
            "should_proceed": result.should_proceed,
            "education": _bounded_context_text(result.education),
            "summary": _bounded_context_text(result.summary),
            "recommendation": _bounded_context_text(result.recommendation),
        })
    if not compact_results:
        return "暂无匹配结果。"
    return json.dumps(compact_results, ensure_ascii=False, separators=(",", ":"))





@trace_agent_step("agent")
def agent_node(state: AgentState) -> dict:
    """The single decision-making Agent. Decides what to do next, or answers directly."""
    updates: dict = {}
    admission_criteria = state.get("admission_criteria")

    if admission_criteria is None:
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        t0 = time.monotonic()
        admission_criteria = _parse_admission_criteria(last_human.content if last_human else "")
        logger.info("llm_call=admission_criteria_parse latency=%.1fms", (time.monotonic() - t0) * 1000)
        updates["admission_criteria"] = admission_criteria
        print(f"📋 招收信息解析完成：{admission_criteria.title or '未命名方向'}")

    system_message = {
        "role": "system",
        "content": AGENT_SYSTEM_PROMPT.format(
            admission_criteria=admission_criteria.model_dump_json(ensure_ascii=False),
            requested_top_k=_state_top_k(state),
            match_results_context=_build_match_results_context(state),
        ),
    }
    context_messages = _select_recent_rounds(state["messages"])
    logger.info(
        "agent_context total_messages=%d selected_messages=%d rounds=%d",
        len(state["messages"]),
        len(context_messages),
        sum(isinstance(message, HumanMessage) for message in context_messages),
    )
    t0 = time.monotonic()
    response = _llm_with_tools.invoke([system_message, *context_messages])
    logger.info("llm_call=agent_decision latency=%.1fms", (time.monotonic() - t0) * 1000)

    completion_issue = None
    if not getattr(response, "tool_calls", None):
        completion_issue = _completion_guard_issue(state, admission_criteria)
    if completion_issue:
        guard_retries = int(state.get("completion_guard_retries", 0) or 0)
        while not getattr(response, "tool_calls", None):
            if guard_retries >= _COMPLETION_GUARD_MAX_RETRIES:
                raise AgentWorkflowIncompleteError(completion_issue)
            guard_retries += 1
            logger.warning(
                "completion_guard retry=%d/%d issue=%s",
                guard_retries,
                _COMPLETION_GUARD_MAX_RETRIES,
                completion_issue,
            )
            repair_system_message = {
                "role": "system",
                "content": (
                    system_message["content"]
                    + "\n\n"
                    + COMPLETION_GUARD_REPAIR_PROMPT.format(
                        issue=completion_issue,
                        attempt=guard_retries,
                        max_retries=_COMPLETION_GUARD_MAX_RETRIES,
                    )
                ),
            }
            t0 = time.monotonic()
            response = _llm_with_tools.invoke([
                repair_system_message,
                *context_messages,
            ])
            logger.info(
                "llm_call=agent_decision_repair latency=%.1fms",
                (time.monotonic() - t0) * 1000,
            )
        updates["completion_guard_retries"] = guard_retries

    updates["messages"] = [response]
    return updates


def route_from_agent(state: AgentState) -> Literal["tools", "__end__"]:
    """Route: agent 要调用工具则去 tools 节点，否则结束（澄清请求或最终报告）。"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "__end__"





def _tool_name_for_call_id(messages: list, tool_call_id: str) -> str | None:
    """反查某个 tool_call_id 对应的工具名（扫描 AIMessage.tool_calls）。"""
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("id") == tool_call_id:
                return call.get("name")
    return None


def _round_start_index(messages: list) -> int:
    """定位"这一轮"的起点——最近一条 HumanMessage 的下标。

    滑动窗口（compress_node）、判断"这一轮是否已经调用过某个工具"
    （_tool_called_earlier_in_round）、提取"这一轮的招生调整说明"
    （api/server.py::_extract_adjustment_note）三处场景都要先定位到同一个
    边界，抽成公共函数，避免各自维护一份可能不一致的实现。
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return i
    return 0


def _completion_guard_issue(state: AgentState, admission_criteria: AdmissionCriteria | None) -> str | None:
    """Return why the current round may not terminate yet, or ``None`` if complete.

    This is deliberately a deterministic workflow check rather than another Agent. It
    only validates tool ordering that the system already requires:

    - a sufficiently specified first request must search before it can finish;
    - updated admission criteria must be followed by a score, while a new search is optional;
    - every search must be followed by a batch score, including an empty search result
      so an adjustment round can replace stale results with an empty result set.
    """
    messages = state["messages"]
    round_start = _round_start_index(messages)
    current_round = messages[round_start:]
    call_names = [
        call.get("name")
        for message in current_round
        for call in (getattr(message, "tool_calls", None) or [])
        if call.get("name")
    ]

    human_count = sum(isinstance(message, HumanMessage) for message in messages)
    is_first_round = round_start == 0 and human_count == 1
    admission_criteria_is_sufficient = bool(
        admission_criteria
        and (
            (admission_criteria.title or "").strip()
            or any((skill or "").strip() for skill in admission_criteria.skills)
        )
    )

    if is_first_round and admission_criteria_is_sufficient and "search_students" not in call_names:
        return "首次匹配的招生信息已经充分，但尚未调用 search_students"

    latest_update = max(
        (index for index, name in enumerate(call_names) if name == "update_admission_criteria"),
        default=-1,
    )
    latest_search = max(
        (index for index, name in enumerate(call_names) if name == "search_students"),
        default=-1,
    )
    latest_score = max(
        (index for index, name in enumerate(call_names) if name == "score_students_batch"),
        default=-1,
    )

    if latest_update >= 0 and latest_score <= latest_update:
        return "期望条件已经更新，但更新后尚未调用 score_students_batch"
    if latest_search >= 0 and latest_score <= latest_search:
        return "学生已经检索，但检索后尚未调用 score_students_batch"
    return None


def _tool_called_earlier_in_round(messages: list, tool_name: str) -> bool:
    """判断这一轮里，除了当前正在处理的最后一条消息之外，更早的消息里有没有
    已经调用过 ``tool_name``。

    用于 tool_executor_node 判断"这一轮更早的时候是否已经调用过
    update_admission_criteria"——是的话，score_students_batch 才需要清空旧的
    student_map/match_map，做真正的"全量替换"（见 tool_executor_node 里的
    调用处）。排除最后一条消息，是因为它就是当前正在处理的这次工具调用本身，
    不应该被误判成"更早已经调用过"。
    """
    round_messages = messages[_round_start_index(messages):-1]
    for message in round_messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == tool_name:
                return True
    return False


def _latest_feedback_text(messages: list) -> str:
    """取最近一条 HumanMessage 的原始文本。update_admission_criteria 用它当
    "HR 这次反馈说了什么"的输入，不依赖 LLM 在工具参数里复述一遍——复述既有
    转述失真的风险，也白白多花一次生成长文本的时间。
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


@trace_agent_step("compress")
def compress_node(state: AgentState) -> dict:
    """Keep only the newest complete dialogue rounds after a ReAct run finishes.

    ``REMOVE_ALL_MESSAGES`` followed by the retained messages rebuilds the list in its
    original order. This differs from deleting individual ToolMessages and appending
    replacements, which can separate an AI tool call from its required response.
    """
    messages = state["messages"]
    recent_messages = _select_recent_rounds(messages)
    if len(recent_messages) == len(messages):
        return {}
    removed_count = len(messages) - len(recent_messages)
    logger.info(
        "context_window removed_messages=%d retained_messages=%d retained_rounds=%d",
        removed_count,
        len(recent_messages),
        sum(isinstance(message, HumanMessage) for message in recent_messages),
    )
    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *recent_messages,
        ]
    }





@trace_agent_step("tools")
def tool_executor_node(state: AgentState) -> dict:
    """Execute the tool calls the agent requested, updating graph state as needed."""
    last_message = state["messages"][-1]
    tool_messages = []

    student_map: dict[str, StudentProfile] = {}




    key_to_name: dict[str, str] = {}
    for student in state.get("students", []):
        coerced = _coerce_student(student)
        key = _student_key(coerced)
        student_map[key] = coerced
        key_to_name[key] = coerced.name

    match_map: dict[str, MatchResult] = {}
    for result in state.get("match_results", []):
        coerced = _coerce_match_result(result)
        match_map[coerced.student_name] = coerced





    last_search_result_json = state.get("last_search_result_json")



    admission_criteria_update: AdmissionCriteria | None = None








    requirements_updated_earlier = _tool_called_earlier_in_round(
        state["messages"], "update_admission_criteria"
    )

    for tool_call in last_message.tool_calls:
        name = tool_call["name"]
        print(f"⚙️  调用工具：{name}")
        t0 = time.monotonic()

        if name == "score_students_batch":





            args = dict(tool_call["args"])
            if last_search_result_json is not None:
                args["students_json"] = last_search_result_json
            admission_criteria_for_scoring = state.get("admission_criteria")
            if admission_criteria_for_scoring is not None:
                args["admission_criteria_json"] = admission_criteria_for_scoring.model_dump_json(ensure_ascii=False)
            if requirements_updated_earlier:



                student_map.clear()
                match_map.clear()
                key_to_name.clear()
            raw = TOOLS_BY_NAME[name].invoke(args)
            parsed = json.loads(raw)
            trimmed = []
            for item in parsed:
                student = StudentProfile.model_validate(item["student"])
                match_result = MatchResult.model_validate(item["match_result"])
                student_key = _student_key(student)

                existing_name = key_to_name.get(student_key)
                if existing_name is not None and existing_name in match_map:


                    match_result.student_name = existing_name
                    student.name = existing_name
                else:
                    unique_name = _dedupe_display_name(match_result.student_name, set(match_map))
                    if unique_name != match_result.student_name:
                        match_result.student_name = unique_name
                        student.name = unique_name

                student_map[student_key] = student
                match_map[match_result.student_name] = match_result
                key_to_name[student_key] = match_result.student_name
                trimmed.append({
                    "student_name": match_result.student_name,
                    "match_score": match_result.match_score,
                    "matched_skills": match_result.matched_skills,
                    "missing_skills": match_result.missing_skills,
                    "should_proceed": match_result.should_proceed,
                })
            content = json.dumps(trimmed, ensure_ascii=False)
        elif name == "search_students":



            args = dict(tool_call["args"])
            args["top_k"] = _state_top_k(state)
            args["owner_user_id"] = state["owner_user_id"]
            raw_search_result = TOOLS_BY_NAME[name].invoke(args)
            last_search_result_json, student_count = _validate_search_result(
                raw_search_result
            )



            content = json.dumps({
                "status": "ok",
                "tool": "search_students",
                "student_count": student_count,
                "next_action": "call score_students_batch",
            }, ensure_ascii=False, separators=(",", ":"))
        elif name == "update_admission_criteria":





            args = dict(tool_call["args"])
            current_admission_criteria = state.get("admission_criteria")
            args["admission_criteria_json"] = current_admission_criteria.model_dump_json(ensure_ascii=False) if current_admission_criteria else ""
            args["feedback_text"] = _latest_feedback_text(state["messages"])
            content = TOOLS_BY_NAME[name].invoke(args)
            try:
                admission_criteria_update = AdmissionCriteriaUpdateResult.model_validate_json(content).admission_criteria
            except Exception as exc:
                logger.warning("解析 update_admission_criteria 结果失败，招生信息保持不变: %s", exc)
                admission_criteria_update = current_admission_criteria
        else:
            content = TOOLS_BY_NAME[name].invoke(tool_call["args"])

        log_tool_usage(name, tool_call["args"], content, (time.monotonic() - t0) * 1000)
        tool_messages.append({"role": "tool", "content": content, "tool_call_id": tool_call["id"]})

    sorted_matches = sorted(match_map.values(), key=lambda item: item.match_score, reverse=True)
    result = {
        "messages": tool_messages,
        "students": list(student_map.values()),
        "match_results": sorted_matches,
        "last_search_result_json": last_search_result_json,
    }
    if admission_criteria_update is not None:
        result["admission_criteria"] = admission_criteria_update
    return result
