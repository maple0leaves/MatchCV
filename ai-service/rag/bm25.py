"""手写 BM25 关键词检索实现，供混合检索（语义 + 关键词加权融合）使用。

不引入 ``rank_bm25`` 第三方依赖。BM25 公式本身较小，内置实现可以减少额外的
版本兼容风险，并方便针对中文分词结果进行调整。

BM25 核心思想：给定查询词，综合三个因素给文档打分——
1. 词频饱和（TF saturation）：一个词在文档里出现得越多，加分越多，但边际收益
   递减（出现 10 次不会是出现 1 次的 10 倍分数），避免长文档靠堆砌关键词刷分。
2. 逆文档频率（IDF）：越少文档包含的词（越"少见"），命中时权重越高；几乎所有
   文档都有的词（比如"经验""负责"）权重趋近于 0。
3. 文档长度归一化：长文档天然词频更高，需要按文档长度相对语料平均长度打折，
   避免长文档仅因为字数多就获得不公平的高分。
"""

from __future__ import annotations

import math
import re
from collections import Counter

import jieba

# BM25 标准参数（Robertson/Sparck Jones 原始论文及后续实践中最常用的默认值）：
# k1 控制词频饱和速度（越大，词频的边际收益衰减越慢）；
# b 控制文档长度归一化强度（0 表示完全不考虑长度，1 表示完全按长度线性折算）。
_BM25_K1 = 1.5
_BM25_B = 0.75

# 英文单词/技术符号（Java、C++、3年、Spring Boot 里的 "Boot"）按原样整体匹配；
# 其余（中文）片段单独交给 jieba 分词，避免 jieba 把中英混排文本切碎、
# 也避免技术词汇被中文分词器拆散成无意义的字。
_LATIN_TOKEN_RE = re.compile(r"[a-zA-Z0-9+#._-]+")


def tokenize(text: str) -> list[str]:
    """中英文混合分词：拉丁字符/数字片段整体保留，中文片段用 jieba 分词。"""
    if not text:
        return []
    tokens: list[str] = []
    pos = 0
    lower_text = text.lower()
    for match in _LATIN_TOKEN_RE.finditer(lower_text):
        if match.start() > pos:
            tokens.extend(_cut_chinese(text[pos : match.start()]))
        tokens.append(match.group(0))
        pos = match.end()
    if pos < len(text):
        tokens.extend(_cut_chinese(text[pos:]))
    return tokens


def _cut_chinese(segment: str) -> list[str]:
    return [term.strip().lower() for term in jieba.cut(segment) if term.strip()]


class BM25Index:
    """内存态 BM25 索引，按候选人（而非简历 chunk）粒度构建。

    为什么按候选人粒度而不是 chunk 粒度：pgvector 表里一份简历会被切成多个
    chunk（``rag/vector_store.py`` 的 ``chunk_size=800``），如果按 chunk 建索引，
    还需要一套"多个 chunk 分数聚合成候选人分数"的额外逻辑，且语义检索那侧
    （``PgVectorResumeStore.similarity_search``）已经是直接按候选人去重返回的。
    这里在构建索引前，直接把同一候选人的所有 chunk 拼接成一份完整文本
    （见 ``rag/vector_store.py::load_candidate_corpus``），两侧检索粒度对齐，
    融合时不需要再处理"候选人 vs chunk"的映射关系。
    """

    def __init__(self, documents: list[tuple[str, str, str]]):
        """``documents``: [(source, name, full_text), ...]，每个候选人一行。"""
        self._sources: list[str] = []
        self._names: dict[str, str] = {}
        self._texts: dict[str, str] = {}
        doc_freqs: list[Counter] = []
        doc_lens: list[int] = []
        term_doc_count: Counter = Counter()

        for source, name, text in documents:
            tokens = tokenize(text)
            freqs = Counter(tokens)
            self._sources.append(source)
            self._names[source] = name
            self._texts[source] = text
            doc_freqs.append(freqs)
            doc_lens.append(len(tokens))
            for term in freqs:
                term_doc_count[term] += 1

        self._doc_freqs = doc_freqs
        self._doc_lens = doc_lens
        self._n_docs = len(documents)
        self._avg_doc_len = (sum(doc_lens) / self._n_docs) if self._n_docs else 0.0
        self._idf: dict[str, float] = {
            term: math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1)
            for term, df in term_doc_count.items()
        }

    @property
    def size(self) -> int:
        return self._n_docs

    def get_text(self, source: str) -> str | None:
        return self._texts.get(source)

    def get_name(self, source: str) -> str | None:
        return self._names.get(source)

    def score(self, query: str) -> dict[str, float]:
        """返回 {source: bm25_score}，覆盖索引里的全部候选人（未命中任何查询词的为 0）。"""
        if self._n_docs == 0:
            return {}
        query_terms = tokenize(query)
        scores: dict[str, float] = {source: 0.0 for source in self._sources}
        if not query_terms:
            return scores

        for source, freqs, doc_len in zip(self._sources, self._doc_freqs, self._doc_lens):
            length_norm = 1 - _BM25_B + _BM25_B * (
                doc_len / self._avg_doc_len if self._avg_doc_len else 0.0
            )
            total = 0.0
            for term in query_terms:
                idf = self._idf.get(term)
                f = freqs.get(term, 0)
                if not idf or f == 0:
                    continue
                total += idf * (f * (_BM25_K1 + 1)) / (f + _BM25_K1 * length_norm)
            scores[source] = total
        return scores
