"""Global configuration for the admission system."""

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



OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "8"))




EMBEDDING_TIMEOUT = float(os.getenv("EMBEDDING_TIMEOUT", "20"))


LLM_STRUCTURED_METHOD = os.getenv("LLM_STRUCTURED_METHOD", "json_mode")



LLM_DISABLE_THINKING = os.getenv("LLM_DISABLE_THINKING", "true").lower() == "true"
LLM_FORCE_FALLBACK = os.getenv("LLM_FORCE_FALLBACK", "false").lower() == "true"
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "")
LLM_FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
LLM_FALLBACK_STRUCTURED_METHOD = os.getenv("LLM_FALLBACK_STRUCTURED_METHOD", "json_mode")



SCORE_CALIBRATION_ENABLED = os.getenv("SCORE_CALIBRATION_ENABLED", "true").lower() == "true"




SCORE_CALIBRATION_RULE_WEIGHT = float(os.getenv("SCORE_CALIBRATION_RULE_WEIGHT", "0.7"))
SCORE_CALIBRATION_LLM_WEIGHT = float(os.getenv("SCORE_CALIBRATION_LLM_WEIGHT", "0.3"))








SCORE_CALIBRATION_MAX_RESUME_CHARS = int(os.getenv("SCORE_CALIBRATION_MAX_RESUME_CHARS", "5000"))





EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or OPENAI_API_KEY
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL") or OPENAI_BASE_URL








OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
OCR_MODEL = os.getenv("OCR_MODEL", "deepseek-ai/DeepSeek-OCR")
OCR_API_KEY = os.getenv("OCR_API_KEY") or EMBEDDING_API_KEY
OCR_BASE_URL = os.getenv("OCR_BASE_URL") or EMBEDDING_BASE_URL


OCR_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv(
        "OCR_FALLBACK_MODELS",
        "Qwen/Qwen3-VL-8B-Instruct,PaddlePaddle/PaddleOCR-VL-1.5",
    ).split(",")
    if m.strip()
]


OCR_TIMEOUT_SECONDS = float(os.getenv("OCR_TIMEOUT_SECONDS", "30"))


VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "pgvector")
VECTOR_STORE_PATH = _resolve_path(os.getenv("VECTOR_STORE_PATH", "data/vector_store"))
RESUME_DIR = _resolve_path(os.getenv("RESUME_DIR", "data/resumes"))

PGVECTOR_HOST = os.getenv("PGVECTOR_HOST", "localhost")
PGVECTOR_PORT = int(os.getenv("PGVECTOR_PORT", "5433"))
PGVECTOR_DB = os.getenv("PGVECTOR_DB", "resume_vectors")
PGVECTOR_USER = os.getenv("PGVECTOR_USER", "matchcv")
PGVECTOR_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "matchcv")
PGVECTOR_TABLE = os.getenv("PGVECTOR_TABLE", "resume_vectors")


EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "openai")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))

VECTOR_INDEX_AUTO_REBUILD = os.getenv("VECTOR_INDEX_AUTO_REBUILD", "true").lower() == "true"


RERANK_ENABLED = os.getenv("RERANK_ENABLED", "false").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "jina-reranker-v2-base-multilingual")
RERANK_API_URL = os.getenv("RERANK_API_URL", "")
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "")




CHECKPOINT_DB_PATH = _resolve_path(os.getenv("CHECKPOINT_DB_PATH", "data/checkpoints/checkpoints.db"))


AGENT_RECURSION_LIMIT = max(4, int(os.getenv("AGENT_RECURSION_LIMIT", "12")))


SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))




HYBRID_SEMANTIC_WEIGHT = float(os.getenv("HYBRID_SEMANTIC_WEIGHT", "0.7"))
HYBRID_KEYWORD_WEIGHT = float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.3"))


API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))


ADMISSION_REQUEST_TIMEOUT_SECONDS = float(os.getenv("ADMISSION_REQUEST_TIMEOUT_SECONDS", "90"))



JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production-min-32-bytes!")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
INTERNAL_SERVICE_TOKEN = os.getenv(
    "INTERNAL_SERVICE_TOKEN",
    "dev-internal-token-change-in-production",
)



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
