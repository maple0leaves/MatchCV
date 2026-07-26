"""Tool definitions for the recruitment agent system."""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool

from agent.schemas import CandidateInfo

# 模块级缓存：避免每次工具调用都新建 LLM 客户端 + 重新绑定结构化输出 schema。
# 无状态对象，可安全跨线程共享。
_LLM_RESUME_PARSER = None


def _get_resume_parser():
    """Return a process-wide singleton LLM bound to CandidateInfo schema."""
    global _LLM_RESUME_PARSER
    if _LLM_RESUME_PARSER is None:
        from agent.agent import _build_structured_llm

        _LLM_RESUME_PARSER = _build_structured_llm(CandidateInfo)
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


def _keyword_search_candidates(query: str, top_k: int, owner_user_id: int) -> str:
    """Fallback candidate search when vector embeddings are unavailable."""
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
    r"[\u0400-\u04FF"   # 西里尔字母
    r"\u0600-\u06FF"   # 阿拉伯字母
    r"\u0590-\u05FF]"  # 希伯来字母
)
_LATEX_RE = re.compile(r"\\[a-zA-Z]{2,}")


def _sanitize_parsed_candidate(candidate: CandidateInfo) -> CandidateInfo:
    """把兜底模型幻觉产生的乱码字段置空，防止垃圾数据进入 lru_cache 缓存。

    只清空确认为乱码的字段；其他字段原样保留，让 server.py 的
    ``internal_parse_resume`` 用本地规则解析结果补齐。
    """

    def _is_garbled(text: str) -> bool:
        return bool(_GARBLED_RE.search(text) or _LATEX_RE.search(text))

    if _is_garbled(candidate.name):
        logger.warning("analyze_resume: garbled name detected (%r), clearing", candidate.name[:40])
        candidate = candidate.model_copy(update={"name": ""})
    if _is_garbled(candidate.education):
        candidate = candidate.model_copy(update={"education": ""})
    if _is_garbled(candidate.summary):
        logger.warning("analyze_resume: garbled summary detected, clearing")
        candidate = candidate.model_copy(update={"summary": ""})
    clean_skills = [s for s in candidate.skills if not _is_garbled(s)]
    if len(clean_skills) < len(candidate.skills):
        logger.warning(
            "analyze_resume: dropped %d garbled skill(s)",
            len(candidate.skills) - len(clean_skills),
        )
        candidate = candidate.model_copy(update={"skills": clean_skills})
    return candidate


@lru_cache(maxsize=512)
def _analyze_resume_cached(resume_text: str) -> str:
    """LLM 解析的进程内缓存。同一份简历重复出现时直接返回上次结果。

    直接用 ``resume_text`` 做 lru_cache 的 key 即可——lru_cache 本身就会用
    全部参数做 key（先取 hash 分桶，再用 == 精确比较），额外传一个手动算好的
    md5 摘要进来不会带来任何去重收益，只会多一次哈希计算。

    返回前经过 ``_sanitize_parsed_candidate`` 乱码过滤：主力模型 400 自动
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
    result = _sanitize_parsed_candidate(result)
    return result.model_dump_json(ensure_ascii=False)


@tool
def search_candidates(query: str, top_k: int = 5, owner_user_id: int = 0) -> str:
    """Search candidate resumes from the vector store using semantic similarity.

    Args:
        query: Search query, e.g. "多模态大模型 Python PyTorch"
        top_k: Number of candidates to return

    Returns:
        JSON string of matched candidate summaries
    """
    from config import LLM_FORCE_FALLBACK

    if LLM_FORCE_FALLBACK:
        logger.info("LLM fallback mode enabled; using keyword candidate search")
        return _keyword_search_candidates(query, top_k, owner_user_id)

    from rag.retriever import get_retriever

    try:
        retriever = get_retriever(top_k=top_k, owner_user_id=owner_user_id)
        docs = retriever.invoke(query)
    except Exception as exc:
        logger.warning("Vector candidate search failed, using keyword fallback: %s", exc)
        return _keyword_search_candidates(query, top_k, owner_user_id)
    results = []
    seen_sources: set[str] = set()

    for doc in docs:
        source = doc.metadata.get("source", "")
        if source and source in seen_sources:
            continue
        if source:
            seen_sources.add(source)

        # 优先复用 vector store 已切好的 chunk，避免重复打开 PDF。
        # 仅当 chunk 明显是被切片的片段（无邮箱且很短）才回退去读全文。
        resume_text = doc.page_content
        needs_full_text = source and len(resume_text) < 400 and "@" not in resume_text
        if needs_full_text and Path(source).exists():
            resume_text = _read_resume_file(source)

        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume_text)
        # 注意：tool 返回值会进入 LangGraph messages，会被后续 LLM 调用反复
        # 重发。这里只回传摘要 + source 引用，避免全文污染上下文；worker
        # 拿到 source 后通过 _read_resume_file（已带 LRU 缓存）取全文。
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
    不绑定给招聘匹配 Agent —— 两者是完全独立的业务流程，Agent 的工具列表/
    Prompt 决策规则里都不应该出现它，避免 LLM 在无关场景下被诱导调用。
    """
    return _analyze_resume_cached(resume_text)


@tool
def score_candidates_batch(candidates_json: str, jd_json: str) -> str:
    """Score a batch of retrieved students against admission criteria in parallel.

    Call this once right after search_candidates. Do not call this once per
    candidate — it already parallelizes internally.

    Args:
        candidates_json: Leave this as an empty string. The system automatically
            substitutes the real search_candidates output before running this
            tool — you do NOT need to copy/retype that JSON here, it would only
            waste generation time reproducing content you already saw.
        jd_json: Leave this as an empty string too; the system fills in the
            already-parsed admission criteria automatically.

    Returns:
        JSON string with each student's full profile and match result.
    """
    from concurrent.futures import ThreadPoolExecutor

    from agent.agent import _CANDIDATE_PARALLELISM, _process_one_candidate
    from agent.schemas import JDInfo

    candidates_payload = json.loads(candidates_json) if candidates_json else []
    if not candidates_payload:
        return json.dumps([], ensure_ascii=False)

    try:
        jd_info = JDInfo.model_validate_json(jd_json) if jd_json else None
    except Exception:  # noqa: BLE001
        jd_info = None

    workers = min(_CANDIDATE_PARALLELISM, len(candidates_payload))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = list(pool.map(lambda payload: _process_one_candidate(payload, jd_info), candidates_payload))

    results = []
    for item in processed:
        if item is None:
            continue
        candidate, match_result = item
        results.append({"candidate": candidate.model_dump(), "match_result": match_result.model_dump()})
    return json.dumps(results, ensure_ascii=False)


@tool
def update_job_requirements(jd_json: str, feedback_text: str) -> str:
    """Merge new/changed/removed conditions from feedback into admission criteria.

    Call this when feedback changes the student screening criteria (adds, modifies,
    or removes a skill, education requirement, or another expectation). Do not call
    this for feedback that can be answered directly from existing data without
    changing the criteria.

    Args:
        jd_json: Leave this as an empty string. The system automatically fills in the
            current parsed admission criteria before running this tool.
        feedback_text: Leave this as an empty string too; the system fills in the user's
            latest feedback text automatically.

    Returns:
        JSON string with two fields: jd_info (the updated admission criteria) and
        change_summary (one-sentence description of what changed).
    """
    from agent.agent import _update_job_requirements
    from agent.schemas import JDInfo

    try:
        current_jd = JDInfo.model_validate_json(jd_json) if jd_json else JDInfo()
    except Exception:  # noqa: BLE001
        current_jd = JDInfo()

    result = _update_job_requirements(current_jd, feedback_text)
    return result.model_dump_json(ensure_ascii=False)


logger = logging.getLogger(__name__)

# 绑定给招聘匹配 Agent 的工具列表。注意：analyze_resume 不在这里——它只服务于
# /api/internal/parse-resume（Java 异步上传简历解析），与 Agent 的招聘匹配场景
# 无关，绑定进来只会让 LLM 有机会在决策规则没有覆盖的场景下误调用它。
#
# arbitrate_candidates（仲裁复核）与 score_candidates_batch
# 阶段的 LLM 校准输入几乎一样（同一份简历全文 + JD）、输出语义也一样
# （"要不要微调分数"），只是触发时机和幅度上限不同，本质是对同一件事
# 又问了 LLM 一遍，撑不住"为什么要两层调整机制"的面试追问，因此直接
# 合并成一层，不保留这个语义重叠的复核链路。
ALL_TOOLS: list = [
    search_candidates,
    score_candidates_batch,
    update_job_requirements,
]
TOOLS_BY_NAME: dict = {t.name: t for t in ALL_TOOLS}
