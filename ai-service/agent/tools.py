"""Tool definitions for the admission agent system."""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool

from agent.schemas import StudentProfile



_LLM_RESUME_PARSER = None


def _get_resume_parser():
    """Return a process-wide singleton LLM bound to StudentProfile schema."""
    global _LLM_RESUME_PARSER
    if _LLM_RESUME_PARSER is None:
        from agent.agent import _build_structured_llm

        _LLM_RESUME_PARSER = _build_structured_llm(StudentProfile)
    return _LLM_RESUME_PARSER


def _read_resume_file_uncached(file_path: str) -> str:
    """Read resume content from a .txt or .pdf file."""
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        import fitz

        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages)
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=256)
def _read_resume_file(file_path: str) -> str:
    """Cached resume reader. PDF/TXT 解析结果按文件路径缓存，避免反复读盘。"""
    return _read_resume_file_uncached(file_path)


def _keyword_search_students(query: str, top_k: int, owner_user_id: int) -> str:
    """Fallback student search when vector embeddings are unavailable."""
    from rag.retriever import keyword_search_documents

    docs = keyword_search_documents(query, top_k, owner_user_id)
    results = []
    for doc in docs:
        resume_text = doc.page_content
        source = doc.metadata.get("source", "")
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume_text)
        results.append(
            {
                "name": doc.metadata.get("name", "") or "未知学生",
                "email": email_match.group(0) if email_match else "",
                "content": resume_text[:500],
                "source": source,
            }
        )
    return json.dumps(results, ensure_ascii=False)


_GARBLED_RE = re.compile(
    r"[\u0400-\u04FF"
    r"\u0600-\u06FF"
    r"\u0590-\u05FF]"
)
_LATEX_RE = re.compile(r"\\[a-zA-Z]{2,}")


def _sanitize_parsed_student(student: StudentProfile) -> StudentProfile:
    """把兜底模型幻觉产生的乱码字段置空，防止垃圾数据进入 lru_cache 缓存。

    只清空确认为乱码的字段；其他字段原样保留，让 server.py 的
    ``internal_parse_resume`` 用本地规则解析结果补齐。
    """

    def _is_garbled(text: str) -> bool:
        return bool(_GARBLED_RE.search(text) or _LATEX_RE.search(text))

    if _is_garbled(student.name):
        logger.warning("analyze_resume: garbled name detected (%r), clearing", student.name[:40])
        student = student.model_copy(update={"name": ""})
    if _is_garbled(student.education):
        student = student.model_copy(update={"education": ""})
    if _is_garbled(student.summary):
        logger.warning("analyze_resume: garbled summary detected, clearing")
        student = student.model_copy(update={"summary": ""})
    clean_skills = [s for s in student.skills if not _is_garbled(s)]
    if len(clean_skills) < len(student.skills):
        logger.warning(
            "analyze_resume: dropped %d garbled skill(s)",
            len(student.skills) - len(clean_skills),
        )
        student = student.model_copy(update={"skills": clean_skills})
    return student


@lru_cache(maxsize=512)
def _analyze_resume_cached(resume_text: str) -> str:
    """LLM 解析的进程内缓存。同一份简历重复出现时直接返回上次结果。

    直接用 ``resume_text`` 做 lru_cache 的 key 即可——lru_cache 本身就会用
    全部参数做 key（先取 hash 分桶，再用 == 精确比较），额外传一个手动算好的
    md5 摘要进来不会带来任何去重收益，只会多一次哈希计算。

    返回前经过 ``_sanitize_parsed_student`` 乱码过滤：主力模型 400 自动
    切到兜底模型（DeepSeek-V4-Flash）时，json_mode 偶尔对 name/summary 等字段
    产生幻觉（西里尔/LaTeX/阿拉伯字符），过滤后让 server.py 的规则解析兜底，
    防止乱码结果被缓存并扩散到后续所有相同简历的解析请求。
    """
    from agent.prompt import RESUME_PARSE_PROMPT
    from agent.security import INJECTION_GUARD_SYSTEM, log_if_injection, wrap_untrusted

    log_if_injection(resume_text, "analyze_resume")
    prompt = (
        INJECTION_GUARD_SYSTEM
        + "\n\n"
        + RESUME_PARSE_PROMPT.format(resume_text=wrap_untrusted(resume_text, "resume"))
    )
    result = _get_resume_parser().invoke(prompt)
    result = _sanitize_parsed_student(result)
    return result.model_dump_json(ensure_ascii=False)


@tool
def search_students(query: str, top_k: int = 5, owner_user_id: int = 0) -> str:
    """Search student resumes from the vector store using semantic similarity.

    Args:
        query: Search query, e.g. "多模态大模型 Python PyTorch"
        top_k: Number of students to return

    Returns:
        JSON string of matched student summaries
    """
    from config import LLM_FORCE_FALLBACK

    if LLM_FORCE_FALLBACK:
        logger.info("LLM fallback mode enabled; using keyword student search")
        return _keyword_search_students(query, top_k, owner_user_id)

    from rag.retriever import get_retriever

    try:
        retriever = get_retriever(top_k=top_k, owner_user_id=owner_user_id)
        docs = retriever.invoke(query)
    except Exception as exc:
        logger.warning("Vector student search failed, using keyword fallback: %s", exc)
        return _keyword_search_students(query, top_k, owner_user_id)
    results = []
    seen_sources: set[str] = set()

    for doc in docs:
        source = doc.metadata.get("source", "")
        if source and source in seen_sources:
            continue
        if source:
            seen_sources.add(source)



        resume_text = doc.page_content
        needs_full_text = source and len(resume_text) < 400 and "@" not in resume_text
        if needs_full_text and Path(source).exists():
            resume_text = _read_resume_file(source)

        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume_text)



        results.append(
            {
                "name": doc.metadata.get("name", "Unknown"),
                "email": email_match.group(0) if email_match else doc.metadata.get("email", ""),
                "content": resume_text[:500],
                "source": source,
            }
        )
    return json.dumps(results, ensure_ascii=False)


@tool
def analyze_resume(resume_text: str) -> str:
    """Parse and extract structured information from a resume text.

    仅供 /api/internal/parse-resume（Java 异步上传解析）直接 .invoke() 调用，
    不绑定给招生匹配 Agent —— 两者是完全独立的业务流程，Agent 的工具列表/
    Prompt 决策规则里都不应该出现它，避免 LLM 在无关场景下被诱导调用。
    """
    return _analyze_resume_cached(resume_text)


@tool
def score_students_batch(students_json: str, admission_criteria_json: str) -> str:
    """Score a batch of retrieved students against admission criteria in parallel.

    Call this once right after search_students. Do not call this once per
    student — it already parallelizes internally.

    Args:
        students_json: Leave this as an empty string. The system automatically
            substitutes the real search_students output before running this
            tool — you do NOT need to copy/retype that JSON here, it would only
            waste generation time reproducing content you already saw.
        admission_criteria_json: Leave this as an empty string too; the system fills in the
            already-parsed admission criteria automatically.

    Returns:
        JSON string with each student's full profile and match result.
    """
    from concurrent.futures import ThreadPoolExecutor

    from agent.agent import _STUDENT_PARALLELISM, _process_one_student
    from agent.schemas import AdmissionCriteria

    students_payload = json.loads(students_json) if students_json else []
    if not students_payload:
        return json.dumps([], ensure_ascii=False)

    try:
        admission_criteria = AdmissionCriteria.model_validate_json(admission_criteria_json) if admission_criteria_json else None
    except Exception:
        admission_criteria = None

    workers = min(_STUDENT_PARALLELISM, len(students_payload))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = list(pool.map(lambda payload: _process_one_student(payload, admission_criteria), students_payload))

    results = []
    for item in processed:
        if item is None:
            continue
        student, match_result = item
        results.append({"student": student.model_dump(), "match_result": match_result.model_dump()})
    return json.dumps(results, ensure_ascii=False)


@tool
def update_admission_criteria(admission_criteria_json: str, feedback_text: str) -> str:
    """Merge new/changed/removed conditions from feedback into admission criteria.

    Call this when feedback changes the student screening criteria (adds, modifies,
    or removes a skill, education requirement, or another expectation). Do not call
    this for feedback that can be answered directly from existing data without
    changing the criteria.

    Args:
        admission_criteria_json: Leave this as an empty string. The system automatically fills in the
            current parsed admission criteria before running this tool.
        feedback_text: Leave this as an empty string too; the system fills in the user's
            latest feedback text automatically.

    Returns:
        JSON string with two fields: admission_criteria (the updated admission criteria) and
        change_summary (one-sentence description of what changed).
    """
    from agent.agent import _update_admission_criteria
    from agent.schemas import AdmissionCriteria

    try:
        current_admission_criteria = AdmissionCriteria.model_validate_json(admission_criteria_json) if admission_criteria_json else AdmissionCriteria()
    except Exception:
        current_admission_criteria = AdmissionCriteria()

    result = _update_admission_criteria(current_admission_criteria, feedback_text)
    return result.model_dump_json(ensure_ascii=False)


logger = logging.getLogger(__name__)










ALL_TOOLS: list = [
    search_students,
    score_students_batch,
    update_admission_criteria,
]
TOOLS_BY_NAME: dict = {t.name: t for t in ALL_TOOLS}
