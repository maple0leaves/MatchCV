"""Global configuration for the recruitment system."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
APP_ENV = os.getenv("APP_ENV", "development").lower()


def _resolve_path(path_value: str) -> str:
    """Resolve relative project paths against the project root."""
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((BASE_DIR / path).resolve())


# LLM
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")   # 留空则使用 OpenAI 官方；填 OpenRouter 地址则走 OpenRouter
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "8"))
# 单次 embedding 调用的超时。必须比聊天 LLM 的超时短：这是一次几十字符/几百字的
# 文本转向量调用，正常几十毫秒就返回，不该继承聊天模型那个为"可能思考很久"预留的
# 大额超时预算——否则 langchain_openai 不传 timeout 时会落到 OpenAI SDK 的默认值
# （600 秒），一旦供应商网络抖动，一次 embedding 调用最坏能把请求拖住 10 分钟。
EMBEDDING_TIMEOUT = float(os.getenv("EMBEDDING_TIMEOUT", "20"))
# 部分模型（如 DeepSeek-V4-Flash）的 function_calling 结构化输出不稳定，
# 但支持 json_mode；不兼容时可通过此项切换主模型的结构化输出方式。
LLM_STRUCTURED_METHOD = os.getenv("LLM_STRUCTURED_METHOD", "function_calling")
# DeepSeek-V4-Flash/Pro 等混合思考模型默认开启思考模式，会显著拖慢每次调用
# （实测单次请求可达数十秒）。Agent 场景是多轮工具调用，不需要深度推理，
# 关闭思考模式换取响应速度。仅对识别 enable_thinking 的网关（如硅基流动）生效。
LLM_DISABLE_THINKING = os.getenv("LLM_DISABLE_THINKING", "false").lower() == "true"
LLM_FORCE_FALLBACK = os.getenv("LLM_FORCE_FALLBACK", "false").lower() == "true"
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "")
LLM_FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
LLM_FALLBACK_STRUCTURED_METHOD = os.getenv("LLM_FALLBACK_STRUCTURED_METHOD", "json_mode")

# 混合打分：规则算出一个基线分，LLM 独立打一次语义匹配分，两者按权重加权
# 求和得到最终分数。为 false 时退化为纯规则打分。
SCORE_CALIBRATION_ENABLED = os.getenv("SCORE_CALIBRATION_ENABLED", "true").lower() == "true"
# 规则分 / LLM 语义分各自的权重，默认 70% / 30%。代码会按两者之和归一化，
# 不要求相加正好等于 1。降低 LLM 占比可以减少模型采样波动对最终排序的影响，
# 同时保留它对研究方向、项目深度等规则难以覆盖维度的判断能力。LLM 调用失败
# 时完全回退到规则分（相当于规则权重=100%），不影响批量匹配流程的健壮性。
SCORE_CALIBRATION_RULE_WEIGHT = float(os.getenv("SCORE_CALIBRATION_RULE_WEIGHT", "0.7"))
SCORE_CALIBRATION_LLM_WEIGHT = float(os.getenv("SCORE_CALIBRATION_LLM_WEIGHT", "0.3"))

# LLM 校准阶段简历全文的截断上限（字符数）。之前评估过 Map-Reduce 分块方案，
# 但实测 1 页中文简历提取出的文本约 1400~1600 字，2 页刚好卡在旧的 3000 字
# 阈值线上下，Map-Reduce 在这个量级上"切2块+摘要"带来的价值有限，反而引入
# 切块/并行调用/失败兜底的复杂度；而现有 LLM（DeepSeek 系）上下文窗口普遍
# 64k~128k tokens，直接放宽这个截断上限、单次调用整篇喂给 LLM，比"切块摘要"
# 更简单也更准确（摘要天然有损，原文无损）。5000 字覆盖了绝大多数简历（含
# 2~3 页的长简历），只在极端异常输入时才会真正触断到。
SCORE_CALIBRATION_MAX_RESUME_CHARS = int(os.getenv("SCORE_CALIBRATION_MAX_RESUME_CHARS", "5000"))

# Embedding 的 Key / base_url 默认复用聊天 LLM 的（OPENAI_*），但可以单独覆盖——
# 聊天 LLM 和 embedding 完全可能是两个不同服务商（例如聊天走 DeepSeek 官方 API，
# 但 DeepSeek 官方不提供 embedding 模型，embedding 必须留在提供 BAAI/bge-m3 的
# 硅基流动），所以两者的 base_url/api_key 需要能独立配置，不能绑死在一起。
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or OPENAI_API_KEY
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL") or OPENAI_BASE_URL

# OCR：图片版简历（PNG/JPG）没有可提取的文本层，靠多模态模型识别图片里的文字。
# 默认复用 EMBEDDING_* 那组硅基流动 Key（同一账号）。同账号下实测几款可用模型
# 的时延差距很大（同一张合成简历图）：
#   deepseek-ai/DeepSeek-OCR          ≈ 0.8s   ← 首选
#   Qwen/Qwen3-VL-8B-Instruct         ≈ 6s     ← 备选
#   PaddlePaddle/PaddleOCR-VL-1.5     经常 60s+ / 超时  ← 最后兜底
# 所以默认首选用 DeepSeek-OCR；首选失败/超时再依次换 Qwen、Paddle。
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
OCR_MODEL = os.getenv("OCR_MODEL", "deepseek-ai/DeepSeek-OCR")
OCR_API_KEY = os.getenv("OCR_API_KEY") or EMBEDDING_API_KEY
OCR_BASE_URL = os.getenv("OCR_BASE_URL") or EMBEDDING_BASE_URL
# 跟聊天 LLM 的 OPENAI_*/LLM_FALLBACK_* 主备切换是同一个思路：首选模型超过下面
# 这个"单模型超时"就直接换下一个候选模型重试。留空则只用 OCR_MODEL，不做切换。
OCR_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv(
        "OCR_FALLBACK_MODELS",
        "Qwen/Qwen3-VL-8B-Instruct,PaddlePaddle/PaddleOCR-VL-1.5",
    ).split(",")
    if m.strip()
]
# 每个候选模型单次尝试的超时时间；总的最坏耗时约等于 (1 + len(OCR_FALLBACK_MODELS)) *
# OCR_TIMEOUT_SECONDS，只会在"某个模型确实很慢/挂了"时才会叠加到这个量级。
OCR_TIMEOUT_SECONDS = float(os.getenv("OCR_TIMEOUT_SECONDS", "30"))

# RAG / Vector Store
VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "pgvector")   # pgvector
VECTOR_STORE_PATH = _resolve_path(os.getenv("VECTOR_STORE_PATH", "data/vector_store"))
RESUME_DIR = _resolve_path(os.getenv("RESUME_DIR", "data/resumes"))
# 独立 Postgres 实例，只存简历向量，与业务 MySQL 完全分离。
PGVECTOR_HOST = os.getenv("PGVECTOR_HOST", "localhost")
PGVECTOR_PORT = int(os.getenv("PGVECTOR_PORT", "5433"))
PGVECTOR_DB = os.getenv("PGVECTOR_DB", "resume_vectors")
PGVECTOR_USER = os.getenv("PGVECTOR_USER", "matchcv")
PGVECTOR_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "matchcv")
PGVECTOR_TABLE = os.getenv("PGVECTOR_TABLE", "resume_vectors")
# 使用本地 HuggingFace 模型，无需 OpenAI Key
# 中文推荐：BAAI/bge-small-zh-v1.5（小而快）或 shibing624/text2vec-base-chinese
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "openai")  # openai | huggingface
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
# 为 true 时：每次加载索引前比对简历目录指纹，有增删改则自动全量重建向量索引并刷新内存缓存
VECTOR_INDEX_AUTO_REBUILD = os.getenv("VECTOR_INDEX_AUTO_REBUILD", "true").lower() == "true"

# Rerank（API 模式，兼容 Cohere / Jina / aihubmix）
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "false").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "jina-reranker-v2-base-multilingual")
RERANK_API_URL = os.getenv("RERANK_API_URL", "")   # 留空则自动从 OPENAI_BASE_URL 推导
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "")   # 留空则复用 OPENAI_API_KEY

# Agent 会话持久化（LangGraph checkpointer）
# 用 SQLite 文件持久化 Agent 会话状态，替代重启即丢的 MemorySaver。
# 单实例部署场景下够用；如果以后要多副本水平扩展，需要换成 PostgresSaver。
CHECKPOINT_DB_PATH = _resolve_path(os.getenv("CHECKPOINT_DB_PATH", "data/checkpoints/checkpoints.db"))
# 单次 Agent-Loop 的 LangGraph superstep 上限。正常首轮通常约 6 步，岗位要求
# 调整反馈约 8 步；默认 12 为正常路径留余量，同时避免模型循环漂移。
AGENT_RECURSION_LIMIT = max(4, int(os.getenv("AGENT_RECURSION_LIMIT", "12")))
# 超过这么多天没有新消息的会话，启动时自动清理（checkpoint 数据 + 活跃时间记录），
# 避免 checkpoints.db 随着历史会话数量无限增长。
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))

# 混合检索：语义检索（pgvector 余弦相似度）与关键词检索（BM25）各自归一化后
# 加权融合，替代此前预留但从未真正启用的 API 型 Rerank（RERANK_ENABLED 默认关闭，
# rag/reranker.py 予以保留，以后如需接入外部 Rerank API 仍可启用）。
HYBRID_SEMANTIC_WEIGHT = float(os.getenv("HYBRID_SEMANTIC_WEIGHT", "0.7"))
HYBRID_KEYWORD_WEIGHT = float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.3"))

# API
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
# /api/recruit(/refine) 的总硬上限：不管卡在哪一步（LLM 重试、embedding、pgvector），
# 超过这个时间就直接失败返回，而不是让请求无限期悬着。
RECRUIT_REQUEST_TIMEOUT_SECONDS = float(os.getenv("RECRUIT_REQUEST_TIMEOUT_SECONDS", "90"))

# ── JWT / Auth（Python 只做无状态校验，token 由 Java 端签发，单一 token 模型）──

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production-min-32-bytes!")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
INTERNAL_SERVICE_TOKEN = os.getenv(
    "INTERNAL_SERVICE_TOKEN",
    "dev-internal-token-change-in-production",
)

# ── CORS ───────────────────────────────────────────────────────────────
# Frontend dev server + production domain
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:8000")
CORS_ORIGINS = [origin.strip() for origin in _cors_origins.split(",") if origin.strip()]


def validate_production_config() -> None:
    """Reject development credentials before accepting production traffic."""
    if APP_ENV != "production":
        return
    errors: list[str] = []

    def require_secret(name: str, value: str, forbidden: str, min_length: int) -> None:
        if not value or value == forbidden or len(value) < min_length:
            errors.append(f"{name} 未设置、仍为默认值或长度不足 {min_length} 位")

    require_secret(
        "JWT_SECRET",
        JWT_SECRET,
        "dev-secret-change-in-production-min-32-bytes!",
        32,
    )
    require_secret(
        "INTERNAL_SERVICE_TOKEN",
        INTERNAL_SERVICE_TOKEN,
        "dev-internal-token-change-in-production",
        32,
    )
    require_secret("PGVECTOR_PASSWORD", PGVECTOR_PASSWORD, "matchcv", 16)
    if any(
        "localhost" in origin.lower()
        or "127.0.0.1" in origin
        or origin == "*"
        for origin in CORS_ORIGINS
    ):
        errors.append("CORS_ORIGINS 不能包含 localhost、127.0.0.1 或通配符")
    if errors:
        raise RuntimeError("生产配置校验失败：\n- " + "\n- ".join(errors))
