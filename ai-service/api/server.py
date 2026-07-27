"""FastAPI server exposing the recruitment agent as REST endpoints.

Python 服务只做 AI 能力（简历解析 / 候选人向量索引 / 岗位匹配），业务数据
（用户、候选人、简历文件）全部归口 Java 后端 + MySQL，本服务不直连数据库。
"""

import asyncio
import hmac
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 之前只在各模块里写了 logging.getLogger(__name__).info(...)（工具调用耗时、
# RAG 检索次数等），但从来没有配置任何 handler——root logger 没有 handler 时，
# Python 会用只处理 WARNING 及以上级别的 lastResort handler，INFO 级别的日志
# 全部被默默吞掉，Docker 日志里一条都看不到。这是这次排查"匹配请求为什么慢"
# 时才发现的真实观测性缺口：不是没打日志，是打了但从来没人能看到。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from config import (
    CORS_ORIGINS,
    INTERNAL_SERVICE_TOKEN,
    OCR_FALLBACK_MODELS,
    OCR_TIMEOUT_SECONDS,
    RECRUIT_REQUEST_TIMEOUT_SECONDS,
)
from backend.api.deps import get_current_user

from langchain_core.messages import ToolMessage

from agent.agent import (
    AgentWorkflowIncompleteError,
    _round_start_index,
    _tool_name_for_call_id,
)
from agent.candidate_chat import answer_candidate_question
from agent.schemas import (
    CandidateChatRequest,
    CandidateChatResponse,
    CandidateInfo,
    JDInfo,
    JDUpdateResult,
    MatchResult,
    RecruitmentInput,
    RecruitmentOutput,
)
from main import (
    AgentLoopLimitError,
    SessionAccessDeniedError,
    SessionNotFoundError,
    cleanup_expired_sessions,
    get_session_snapshot,
    refine_session,
    start_session,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
UPLOAD_PARSE_AI_TIMEOUT_SECONDS = 12


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    from config import validate_production_config

    validate_production_config()
    # 启动时清理过期会话，避免 checkpoints.db 随历史会话数量无限增长。
    try:
        await asyncio.to_thread(cleanup_expired_sessions)
    except Exception:
        logger.exception("清理过期会话失败，不影响服务启动")
    yield


app = FastAPI(
    title="MatchCV Student Screening AI Service",
    description="基于 LangChain + LangGraph 的导师招生简历筛选系统（AI 服务层）",
    version="1.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_match_results(match_results: list) -> list[MatchResult]:
    """Normalize match result payloads into MatchResult models."""
    parsed_results: list[MatchResult] = []
    for item in match_results:
        if isinstance(item, MatchResult):
            parsed_results.append(item)
        elif isinstance(item, dict):
            parsed_results.append(MatchResult(**item))
    return parsed_results


def _extract_adjustment_note(result: dict) -> Optional[str]:
    """从这一轮（最近一条 HumanMessage 之后）的消息历史里，判断"调整结果"抽屉
    要不要展示说明、展示什么。

    - 这一轮完全没有调用 update_job_requirements（纯问答/换方向分支）→ None，
      抽屉不展示任何说明，跟改造前行为一致。
    - 调用过 update_job_requirements，也调用过 score_candidates_batch（预期
      的完整三步流程走完了）→ 返回 LLM 写的 change_summary。
    - 调用过 update_job_requirements，但没有调用 score_candidates_batch
      （Agent 没有按预期把三步走完）→ 返回一句提示：当前仍是调整前的旧结果，
      因为 agent.py::tool_executor_node 把"清空旧数据"推迟到 score_candidates_batch
      真正执行时才做，因此这里展示的提示对应当前结果状态。
    """
    messages = result.get("messages", [])
    round_messages = messages[_round_start_index(messages):]

    requirements_updated = False
    change_summary = ""
    rescored = False
    for message in round_messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_name = _tool_name_for_call_id(round_messages, message.tool_call_id)
        if tool_name == "update_job_requirements":
            requirements_updated = True
            try:
                change_summary = JDUpdateResult.model_validate_json(message.content).change_summary
            except Exception:  # noqa: BLE001
                change_summary = ""
        elif tool_name == "score_candidates_batch":
            rescored = True

    if not requirements_updated:
        return None
    if not rescored:
        detail = f"：{change_summary}" if change_summary else ""
        return (
            f"已更新期望条件{detail}，但本轮未完成学生重新检索与打分，"
            "当前仍展示调整前的匹配结果，可以再描述一次需求重试。"
        )
    return change_summary or "期望条件已更新，学生已按新标准重新匹配。"



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return unified JSON for API routes."""
    from fastapi.responses import JSONResponse
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    if request.url.path.startswith(API_PREFIX):
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": "服务器内部错误，请稍后重试", "status_code": 500},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/api/health")
async def health():
    return {"status": "ok"}


async def require_internal_service(
    token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    """Protect Java-to-Python APIs from direct internet access."""
    if not token or not hmac.compare_digest(token, INTERNAL_SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="内部服务认证失败")


def _current_user_id(user: dict) -> int:
    try:
        user_id = int(user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录信息无效，请重新登录")
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="登录信息无效，请重新登录")
    return user_id


def _friendly_ai_error(exc: Exception) -> str:
    detail = str(exc).lower()
    quota_markers = (
        "429", "402", "quota", "rate limit", "rate_limit",
        "insufficient", "余额", "额度", "欠费",
    )
    if any(marker in detail for marker in quota_markers):
        return "AI/OCR 服务额度不足或请求过于频繁，请充值或稍后重试"
    return "AI/OCR 服务暂不可用，请稍后重试"


class InternalParseResumeRequest(BaseModel):
    text: str = Field(min_length=1)


class InternalOcrResumeRequest(BaseModel):
    image_base64: str = Field(min_length=1, description="图片简历的 base64 编码内容")
    image_ext: str = Field(default="png", description="图片格式后缀，如 png/jpg/jpeg")


class InternalIndexCandidateRequest(BaseModel):
    owner_user_id: int = Field(ge=1)
    candidate_id: Optional[int] = None
    name: str = ""
    email: str = ""
    skills: list[str] | str = Field(default_factory=list)
    education: str = ""
    summary: str = ""
    resume_text: str = Field(min_length=1)
    source: str = ""


class CandidateOwnershipMapping(BaseModel):
    owner_user_id: int = Field(ge=1)
    source: str = Field(min_length=1)


class InternalOwnershipSyncRequest(BaseModel):
    candidates: list[CandidateOwnershipMapping] = Field(default_factory=list)


def _local_parse_resume_text(resume_text: str) -> CandidateInfo:
    """Extract enough structured fields to keep uploaded resumes usable."""
    import re

    text = resume_text.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)

    name = ""
    for line in lines[:8]:
        cleaned = re.sub(r"^(姓名|Name|name)[:：]\s*", "", line).strip()
        if email_match and email_match.group(0) in cleaned:
            continue
        if len(cleaned) <= 40 and not re.search(r"[@/\\|,，。；;]", cleaned):
            name = cleaned
            break

    skill_catalog = [
        "Java", "Spring Boot", "Spring Cloud", "MySQL", "Redis", "Python", "Django", "FastAPI",
        "React", "Vue", "TypeScript", "JavaScript", "Node.js", "Docker", "Kubernetes", "Linux",
        "Git", "SQL", "PostgreSQL", "MongoDB", "Elasticsearch", "Flink", "Spark", "Kafka",
        "Figma", "Axure", "CRM", "数据分析", "项目管理", "产品设计", "用户调研", "销售管理",
        "客户管理", "商务谈判",
    ]
    lower_text = text.lower()
    skills = []
    for skill in skill_catalog:
        if skill.lower() in lower_text and skill not in skills:
            skills.append(skill)

    education = ""
    for value in ["博士", "硕士", "研究生", "本科", "大专", "专科"]:
        if value in text:
            education = value
            break

    summary = " ".join(lines[:8])
    return CandidateInfo(
        name=name,
        email=email_match.group(0) if email_match else "",
        skills=skills,
        education=education,
        summary=summary[:800],
    )


def _is_placeholder_text(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return normalized in {
        "candidate",
        "candidate name",
        "unknown",
        "not specified",
        "not specified in input",
        "not specified in the input",
        "not provided",
        "n/a",
        "none",
        "???",
        "未提供",
        "未知",
    }


def _is_garbled_text(value: str | None) -> bool:
    """检测 LLM 兜底模型幻觉输出：西里尔字母、LaTeX 命令、阿拉伯/希伯来字符混入
    中英文字段属于典型幻觉特征，发现即视为乱码，回退规则解析结果。"""
    import re as _re
    if not value:
        return False
    # 西里尔字母（俄语/乌克兰语等）
    if _re.search(r"[\u0400-\u04FF]", value):
        return True
    # LaTeX 命令（如 \alpha、\begin{tabular}）
    if _re.search(r"\\[a-zA-Z]{2,}", value):
        return True
    # 阿拉伯字母
    if _re.search(r"[\u0600-\u06FF]", value):
        return True
    # 希伯来字母
    if _re.search(r"[\u0590-\u05FF]", value):
        return True
    return False


def _format_candidate_index_text(request: InternalIndexCandidateRequest) -> str:
    skills = request.skills
    if isinstance(skills, list):
        skills_text = ", ".join(str(item).strip() for item in skills if str(item).strip())
    else:
        skills_text = str(skills).strip()

    parts = [
        request.resume_text,
        f"姓名：{request.name}" if request.name else "",
        f"邮箱：{request.email}" if request.email else "",
        f"技能：{skills_text}" if skills_text else "",
        f"学历：{request.education}" if request.education else "",
        f"经历摘要：{request.summary}" if request.summary else "",
    ]
    return "\n".join(part.strip() for part in parts if part and part.strip())


@app.post("/api/internal/parse-resume")
async def internal_parse_resume(
    request: InternalParseResumeRequest,
    _internal: None = Depends(require_internal_service),
):
    """Internal Java-backend endpoint for asynchronous uploaded-resume parsing."""
    resume_text = request.text.strip()
    if not resume_text:
        raise HTTPException(status_code=400, detail="简历文本不能为空")

    local_result = _local_parse_resume_text(resume_text)
    try:
        from agent.tools import analyze_resume

        raw = await asyncio.wait_for(
            asyncio.to_thread(analyze_resume.invoke, {"resume_text": resume_text}),
            timeout=UPLOAD_PARSE_AI_TIMEOUT_SECONDS,
        )
        payload = json.loads(raw) if isinstance(raw, str) else raw
        parsed = CandidateInfo.model_validate(payload)
        # 兜底模型（DeepSeek-V4-Flash 等）使用 json_mode 时偶尔对 name/summary
        # 等字段产生幻觉（俄文/LaTeX/阿拉伯字母混入），_is_garbled_text 统一
        # 检测，一旦发现乱码直接用本地规则解析结果替换，避免垃圾数据写入数据库。
        garbled_fields = []
        if _is_placeholder_text(parsed.name) or _is_garbled_text(parsed.name):
            if local_result.name:
                parsed.name = local_result.name
                garbled_fields.append("name")
        if _is_placeholder_text(parsed.email):
            if local_result.email:
                parsed.email = local_result.email
        if not parsed.skills or any(_is_garbled_text(s) for s in parsed.skills):
            if local_result.skills:
                parsed.skills = local_result.skills
                garbled_fields.append("skills")
        if _is_placeholder_text(parsed.education) or _is_garbled_text(parsed.education):
            if local_result.education:
                parsed.education = local_result.education
                garbled_fields.append("education")
        if _is_placeholder_text(parsed.summary) or _is_garbled_text(parsed.summary):
            if local_result.summary:
                parsed.summary = local_result.summary
                garbled_fields.append("summary")
        if garbled_fields:
            logger.warning(
                "AI parse returned garbled/placeholder content in fields %s; "
                "fell back to rule-based values",
                garbled_fields,
            )
        payload = parsed.model_dump()
        payload["processing_warning"] = ""
        return payload
    except Exception as exc:
        logger.warning("AI resume parse failed; returning text parser result: %s", exc)
        payload = local_result.model_dump()
        payload["processing_warning"] = (
            f"{_friendly_ai_error(exc)}；本次已使用本地规则解析，结果可能不完整"
        )
        return payload


@app.post("/api/internal/ocr-resume")
async def internal_ocr_resume(
    request: InternalOcrResumeRequest,
    _internal: None = Depends(require_internal_service),
):
    """Internal Java-backend endpoint：图片简历（PNG/JPG）走 OCR 识别出纯文本。

    只负责"图片 → 文本"，识别出的文本仍会走 Java 那边已有的
    /api/internal/parse-resume 流程做结构化解析，本接口契约与内部实现无关。
    """
    import base64

    try:
        image_bytes = base64.b64decode(request.image_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="image_base64 不是合法的 base64 编码")

    try:
        from ocr.resume_ocr import extract_text_from_image

        # extract_text_from_image 内部会按顺序试 1 个首选 + N 个候选模型，外层超时
        # 要给够所有模型都试一遍的时间，否则会在还没轮到候选模型时就被这里提前掐断。
        model_count = 1 + len(OCR_FALLBACK_MODELS)
        text = await asyncio.wait_for(
            asyncio.to_thread(extract_text_from_image, image_bytes, request.image_ext),
            timeout=OCR_TIMEOUT_SECONDS * model_count + 10,
        )
        return {"text": text}
    except Exception as exc:
        logger.warning("OCR 识别图片简历失败: %s", exc)
        raise HTTPException(status_code=503, detail=_friendly_ai_error(exc))


class InternalDeleteCandidateRequest(BaseModel):
    owner_user_id: int = Field(ge=1)
    source: str = Field(min_length=1)


@app.delete("/api/internal/delete-candidate")
async def internal_delete_candidate(
    request: InternalDeleteCandidateRequest,
    _internal: None = Depends(require_internal_service),
):
    """Internal Java-backend endpoint for removing a candidate's vectors from pgvector."""
    source = request.source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="source 不能为空")

    try:
        from rag.vector_store import delete_resume_document

        deleted = await asyncio.to_thread(
            delete_resume_document, request.owner_user_id, source
        )
        return {"deleted": True, "rows": deleted, "source": source}
    except Exception as exc:
        logger.exception("Failed to delete candidate vectors from pgvector: %s", exc)
        raise HTTPException(status_code=500, detail="从向量库删除候选人失败")


@app.post("/api/internal/index-candidate")
async def internal_index_candidate(
    request: InternalIndexCandidateRequest,
    _internal: None = Depends(require_internal_service),
):
    """Internal Java-backend endpoint for syncing parsed candidates into pgvector."""
    index_text = _format_candidate_index_text(request)
    if not index_text.strip():
        raise HTTPException(status_code=400, detail="候选人简历文本不能为空")

    name = request.name.strip() or f"候选人{request.candidate_id or ''}".strip() or "候选人"
    source = request.source.strip() or (f"candidate:{request.candidate_id}" if request.candidate_id else name)

    try:
        from rag.vector_store import upsert_resume_document

        chunks = await asyncio.to_thread(
            upsert_resume_document,
            owner_user_id=request.owner_user_id,
            name=name,
            source=source,
            text=index_text,
        )
        return {"indexed": True, "chunks": chunks, "source": source}
    except Exception as exc:
        logger.exception("Failed to sync candidate to pgvector: %s", exc)
        raise HTTPException(status_code=500, detail="同步候选人到向量库失败")


@app.post("/api/internal/sync-vector-ownership")
async def internal_sync_vector_ownership(
    request: InternalOwnershipSyncRequest,
    _internal: None = Depends(require_internal_service),
):
    """Attach owners to vector rows created before multi-user isolation."""
    from rag.vector_store import sync_vector_ownership

    mappings = [
        (item.owner_user_id, item.source.strip())
        for item in request.candidates
        if item.source.strip()
    ]
    updated = await asyncio.to_thread(sync_vector_ownership, mappings)
    return {"updated_rows": updated, "candidate_count": len(mappings)}


@app.post("/api/recruit", response_model=RecruitmentOutput)
async def recruit(request: RecruitmentInput, _user: dict = Depends(get_current_user)):
    """Start a new matching session: 招收方向+期望条件 → 学生匹配结果 + session_id。"""
    session_id = uuid4().hex
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                start_session,
                session_id,
                request.user_input,
                request.top_k,
                _current_user_id(_user),
            ),
            timeout=RECRUIT_REQUEST_TIMEOUT_SECONDS,
        )
        return RecruitmentOutput(
            session_id=session_id,
            match_results=_parse_match_results(result.get("match_results", [])),
        )
    except asyncio.TimeoutError:
        # 兜底总时限：不管具体卡在 LLM 重试、embedding 还是别的环节，超时就直接
        # 失败返回，避免请求无限期悬着。
        logger.warning("recruit timed out after %ss, session_id=%s", RECRUIT_REQUEST_TIMEOUT_SECONDS, session_id)
        raise HTTPException(status_code=504, detail="匹配超时，请稍后重试")
    except AgentLoopLimitError:
        logger.warning("recruit agent loop limit reached, session_id=%s", session_id)
        raise HTTPException(status_code=503, detail="匹配执行步骤过多，请简化期望条件后重试")
    except AgentWorkflowIncompleteError:
        logger.warning("recruit agent workflow incomplete, session_id=%s", session_id)
        raise HTTPException(status_code=503, detail="匹配流程未完整执行，请重试")
    except Exception as e:
        raise HTTPException(status_code=503, detail=_friendly_ai_error(e))


class RecruitmentRefineRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


@app.post("/api/recruit/refine", response_model=RecruitmentOutput)
async def recruit_refine(request: RecruitmentRefineRequest, _user: dict = Depends(get_current_user)):
    """Continue an existing session with user feedback, or answer a prior clarification request."""
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                refine_session,
                request.session_id,
                request.message,
                _current_user_id(_user),
            ),
            timeout=RECRUIT_REQUEST_TIMEOUT_SECONDS,
        )
        return RecruitmentOutput(
            session_id=request.session_id,
            match_results=_parse_match_results(result.get("match_results", [])),
            adjustment_note=_extract_adjustment_note(result),
        )
    except asyncio.TimeoutError:
        logger.warning("recruit/refine timed out after %ss, session_id=%s", RECRUIT_REQUEST_TIMEOUT_SECONDS, request.session_id)
        raise HTTPException(status_code=504, detail="匹配超时，请稍后重试")
    except AgentLoopLimitError:
        logger.warning("recruit/refine agent loop limit reached, session_id=%s", request.session_id)
        raise HTTPException(status_code=503, detail="本次调整执行步骤过多，请简化反馈后重试")
    except AgentWorkflowIncompleteError:
        logger.warning("recruit/refine agent workflow incomplete, session_id=%s", request.session_id)
        raise HTTPException(status_code=503, detail="本次调整流程未完整执行，请重试")
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在或已失效，请重新发起匹配")
    except SessionAccessDeniedError:
        # 与不存在统一返回 404，避免通过 session_id 探测其他用户的数据。
        raise HTTPException(status_code=404, detail="会话不存在或已失效，请重新发起匹配")
    except Exception as e:
        raise HTTPException(status_code=503, detail=_friendly_ai_error(e))


@app.post("/api/recruit/candidate-chat", response_model=CandidateChatResponse)
async def candidate_chat(
    request: CandidateChatRequest,
    _user: dict = Depends(get_current_user),
):
    """Answer a read-only question about one authoritative candidate in one owned session."""
    try:
        state = await asyncio.to_thread(
            get_session_snapshot,
            request.session_id,
            _current_user_id(_user),
        )
        jd_value = state.get("jd_info")
        if not jd_value:
            raise HTTPException(status_code=409, detail="当前会话还没有可用的招收信息")
        jd_info = jd_value if isinstance(jd_value, JDInfo) else JDInfo(**jd_value)

        match_result = next(
            (
                item
                for item in _parse_match_results(state.get("match_results", []))
                if item.resume_source == request.resume_source
            ),
            None,
        )
        if match_result is None:
            raise HTTPException(status_code=404, detail="当前会话中不存在这名学生")

        answer = await asyncio.wait_for(
            asyncio.to_thread(
                answer_candidate_question,
                jd_info,
                match_result,
                request.history,
                request.message,
            ),
            timeout=RECRUIT_REQUEST_TIMEOUT_SECONDS,
        )
        return CandidateChatResponse(answer=answer)
    except asyncio.TimeoutError:
        logger.warning(
            "candidate chat timed out after %ss, session_id=%s",
            RECRUIT_REQUEST_TIMEOUT_SECONDS,
            request.session_id,
        )
        raise HTTPException(status_code=504, detail="学生分析超时，请稍后重试")
    except (SessionNotFoundError, SessionAccessDeniedError):
        # 与续聊接口一致，避免通过 session_id 探测其他用户的会话。
        raise HTTPException(status_code=404, detail="会话不存在或已失效，请重新发起匹配")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("candidate chat failed, session_id=%s", request.session_id)
        raise HTTPException(status_code=503, detail="学生分析暂时不可用，请稍后重试") from exc


if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT

    uvicorn.run("api.server:app", host=API_HOST, port=API_PORT, reload=False)
