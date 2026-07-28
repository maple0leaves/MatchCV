"""API-based reranking for the admission RAG pipeline.

Calls a Cohere-compatible rerank endpoint (supported by Cohere, Jina AI,
aihubmix, and most API aggregators). Falls back to score-order truncation
when reranking is disabled or the API call fails.
"""

import logging
import os

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

RERANK_ENABLED = os.getenv("RERANK_ENABLED", "false").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "jina-reranker-v2-base-multilingual")
RERANK_API_URL = os.getenv(
    "RERANK_API_URL",
    os.getenv("OPENAI_BASE_URL", "").rstrip("/").replace("/v1", "") + "/v1/rerank"
    if os.getenv("OPENAI_BASE_URL")
    else "https://api.jina.ai/v1/rerank",
)
RERANK_API_KEY = os.getenv("RERANK_API_KEY") or os.getenv("OPENAI_API_KEY", "")


def _call_rerank_api(query: str, documents: list[str], top_n: int) -> list[dict] | None:
    """Call Cohere-compatible rerank API and return results list or None on failure."""
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed, reranking disabled. Run: pip install httpx")
        return None

    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n,
    }
    headers = {
        "Authorization": f"Bearer {RERANK_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(RERANK_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or data.get("data") or []
            logger.info(
                "Rerank API returned %d results (model=%s)", len(results), RERANK_MODEL
            )
            return results
    except Exception as exc:
        logger.warning("Rerank API call failed, falling back to original order: %s", exc)
        return None


def rerank_documents(
    query: str,
    docs: list[Document],
    top_k: int,
) -> list[Document]:
    """Rerank documents via API and return the top_k most relevant ones.

    Falls back to returning the original docs (truncated to top_k) when
    reranking is disabled or the API call fails.
    """
    if not docs:
        return docs

    if not RERANK_ENABLED:
        logger.debug("Reranking disabled (RERANK_ENABLED=false)")
        return docs[:top_k]

    texts = [doc.page_content for doc in docs]
    results = _call_rerank_api(query, texts, top_n=top_k)

    if not results:
        return docs[:top_k]

    reranked: list[Document] = []
    for item in results:
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(docs):
            reranked.append(docs[idx])

    if not reranked:
        return docs[:top_k]

    scores = [item.get("relevance_score", 0) for item in results]
    logger.info(
        "Rerank complete: %d → top %d (score range: %.4f ~ %.4f)",
        len(docs),
        len(reranked),
        min(scores),
        max(scores),
    )
    return reranked
