"""Retriever interface for the recruitment RAG pipeline.

混合检索：语义检索（pgvector 余弦相似度）+ 关键词检索（BM25）各自归一化后
加权融合，权重见 config.HYBRID_SEMANTIC_WEIGHT / HYBRID_KEYWORD_WEIGHT
（默认语义 0.7 / 关键词 0.3）。替代此前预留但从未真正启用的 API 型 Rerank
（``rag/reranker.py`` 予以保留，RERANK_ENABLED 默认关闭，以后如需接入外部
Rerank API 仍可启用，两者不冲突）。
"""

from __future__ import annotations

import sys
import os
from typing import Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_vector_store = None
_bm25_indexes: dict[int, object] = {}


def invalidate_vector_store_cache() -> None:
    """丢弃内存中的向量库/BM25 索引实例。在磁盘上 ``build_vector_store``/
    ``upsert_resume_document`` 之后调用，避免仍用旧索引。"""
    global _vector_store, _bm25_indexes
    _vector_store = None
    _bm25_indexes = {}


def _get_vector_store():
    global _vector_store
    if _vector_store is None:
        from config import VECTOR_STORE_PATH
        from rag.vector_store import load_vector_store

        # 候选人只能由带 owner_user_id 的内部写入接口建立索引。这里绝不扫描
        # 共享简历目录自动建库，否则无法可靠恢复每份历史文件的所有者。
        _vector_store = load_vector_store(VECTOR_STORE_PATH)
    return _vector_store


def _get_bm25_index(owner_user_id: int):
    global _bm25_indexes
    if owner_user_id not in _bm25_indexes:
        from rag.bm25 import BM25Index
        from rag.vector_store import load_candidate_corpus

        _bm25_indexes[owner_user_id] = BM25Index(load_candidate_corpus(owner_user_id))
    return _bm25_indexes[owner_user_id]


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    """Min-max 归一化到 [0,1]。语义相似度（0~1 附近）和 BM25 分数（量纲不定，
    可能是几到几十）完全不在一个尺度上，必须先归一化才能加权求和。"""
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        # 所有候选人分数相同（含只有一个候选人的情况），归一化没有意义，统一给满分，
        # 避免除以 0，也避免出现"分数相同却排序不公平"的假象。
        return {source: 1.0 for source in scores}
    return {source: (value - lo) / (hi - lo) for source, value in scores.items()}


class HybridRetriever(BaseRetriever):
    """语义检索 + BM25 关键词检索加权融合。

    流程：
    1. 语义检索召回 ``top_k * fetch_k_multiplier`` 个候选人（pgvector 余弦相似度，
       已经按候选人去重，见 PgVectorResumeStore.similarity_search）。
    2. BM25 对全量候选人语料打分，取分数最高的 ``top_k * fetch_k_multiplier`` 个。
    3. 两份候选人列表取并集；分别在各自的参与融合集合内做 min-max 归一化；
       某候选人若只在其中一路的候选列表里出现，另一路按 0 分处理
       （相当于"该方法认为其不够相关，不在其召回范围内"）。
    4. final_score = HYBRID_SEMANTIC_WEIGHT * 语义分 + HYBRID_KEYWORD_WEIGHT * 关键词分，
       按 final_score 降序返回 top_k。
    """

    owner_user_id: int
    top_k: int = 5
    fetch_k_multiplier: int = 3

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None,
    ) -> list[Document]:
        from agent.observability import log_rag_retrieval
        from config import HYBRID_KEYWORD_WEIGHT, HYBRID_SEMANTIC_WEIGHT

        fetch_k = self.top_k * self.fetch_k_multiplier

        store = _get_vector_store()
        semantic_docs = store.similarity_search(
            query, k=fetch_k, owner_user_id=self.owner_user_id
        )
        semantic_scores = {
            doc.metadata.get("source", ""): doc.metadata.get("score", 0.0) for doc in semantic_docs
        }
        docs_by_source: dict[str, Document] = {
            doc.metadata.get("source", ""): doc for doc in semantic_docs
        }

        bm25_index = _get_bm25_index(self.owner_user_id)
        all_keyword_scores = bm25_index.score(query)
        top_keyword_sources = sorted(all_keyword_scores.items(), key=lambda item: item[1], reverse=True)[
            :fetch_k
        ]
        keyword_scores = dict(top_keyword_sources)
        for source, _ in top_keyword_sources:
            if source not in docs_by_source:
                text = bm25_index.get_text(source) or ""
                docs_by_source[source] = Document(
                    page_content=text,
                    metadata={"name": bm25_index.get_name(source) or "", "source": source},
                )

        norm_semantic = _normalize(semantic_scores)
        norm_keyword = _normalize(keyword_scores)

        fused: list[tuple[float, Document]] = []
        for source, doc in docs_by_source.items():
            final_score = (
                HYBRID_SEMANTIC_WEIGHT * norm_semantic.get(source, 0.0)
                + HYBRID_KEYWORD_WEIGHT * norm_keyword.get(source, 0.0)
            )
            fused.append((final_score, doc))
        fused.sort(key=lambda item: item[0], reverse=True)

        results = [doc for _, doc in fused[: self.top_k]]
        log_rag_retrieval(query, len(results), reranked=True)
        return results


def keyword_search_documents(query: str, top_k: int, owner_user_id: int) -> list[Document]:
    """Return owner-scoped BM25 results for the no-embedding fallback path."""
    index = _get_bm25_index(owner_user_id)
    scores = index.score(query)
    sources = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [
        Document(
            page_content=index.get_text(source) or "",
            metadata={"name": index.get_name(source) or "", "source": source},
        )
        for source in sources
    ]


def get_retriever(top_k: int = 5, owner_user_id: int | None = None) -> HybridRetriever:
    """Return a hybrid (semantic + keyword) retriever.
    Drop-in replacement for the previous single-stage retriever.
    The caller interface (``retriever.invoke(query)``) stays the same.
    """
    if owner_user_id is None:
        raise ValueError("owner_user_id is required for candidate retrieval")
    return HybridRetriever(top_k=top_k, owner_user_id=owner_user_id)
