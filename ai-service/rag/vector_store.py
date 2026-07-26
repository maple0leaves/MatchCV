"""Vector store builder for resume documents (PostgreSQL + pgvector)."""

import json
import threading
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

_PG_CONNECTIONS: dict[tuple, object] = {}
_PG_CONNECTION_LOCK = threading.Lock()


def _dsn_key() -> tuple:
    from config import PGVECTOR_DB, PGVECTOR_HOST, PGVECTOR_PASSWORD, PGVECTOR_PORT, PGVECTOR_USER

    return (PGVECTOR_HOST, PGVECTOR_PORT, PGVECTOR_DB, PGVECTOR_USER, PGVECTOR_PASSWORD)


def _get_connection():
    """Return a cached, live psycopg2 connection (reconnect if it died)."""
    import psycopg2
    from pgvector.psycopg2 import register_vector

    from config import PGVECTOR_DB, PGVECTOR_HOST, PGVECTOR_PASSWORD, PGVECTOR_PORT, PGVECTOR_USER

    key = _dsn_key()
    with _PG_CONNECTION_LOCK:
        conn = _PG_CONNECTIONS.get(key)
        if conn is not None and not conn.closed:
            return conn
        conn = psycopg2.connect(
            host=PGVECTOR_HOST,
            port=PGVECTOR_PORT,
            dbname=PGVECTOR_DB,
            user=PGVECTOR_USER,
            password=PGVECTOR_PASSWORD,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        _PG_CONNECTIONS[key] = conn
        return conn


def _table_exists(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        return cur.fetchone()[0] is not None


def _table_dim(conn, table: str) -> int | None:
    """已建表的向量列维度（pgvector 的 typmod 就是维度本身）。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = %s AND a.attname = 'vector' AND a.attnum > 0
            """,
            (table,),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] and row[0] > 0 else None


def _ensure_resume_table(conn, table: str, dim: int, recreate: bool = False) -> None:
    if _table_exists(conn, table):
        current_dim = _table_dim(conn, table)
        if current_dim is not None and current_dim != dim and not recreate:
            raise RuntimeError(
                "Embedding 向量维度与现有索引不一致；为避免自动删除全部用户的向量数据，"
                "请先备份，再通过受控的全量重建流程迁移索引"
            )
        if recreate:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{table}"')
        else:
            with conn.cursor() as cur:
                cur.execute(
                    f'ALTER TABLE "{table}" '
                    "ADD COLUMN IF NOT EXISTS owner_user_id BIGINT NOT NULL DEFAULT 0"
                )
                cur.execute(
                    f'CREATE INDEX IF NOT EXISTS "{table}_owner_source_idx" '
                    f'ON "{table}" (owner_user_id, source)'
                )
            return

    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE "{table}" (
                id BIGSERIAL PRIMARY KEY,
                owner_user_id BIGINT NOT NULL,
                vector vector({dim}) NOT NULL,
                text TEXT NOT NULL,
                name VARCHAR(512) NOT NULL DEFAULT '',
                source VARCHAR(1024) NOT NULL DEFAULT ''
            )
            """
        )
        cur.execute(f'CREATE INDEX ON "{table}" (owner_user_id, source)')
        # HNSW：该数据量级下构建快、查询快，优于 IVFFlat（不需要预先估算 lists 数）。
        cur.execute(
            f'CREATE INDEX ON "{table}" USING hnsw (vector vector_cosine_ops)'
        )


def _delete_existing_source(conn, table: str, owner_user_id: int, source: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'DELETE FROM "{table}" WHERE owner_user_id = %s AND source = %s',
                (owner_user_id, source[:1024]),
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[VectorStore] 删除旧候选人向量失败，继续插入新向量：{exc}", flush=True)


def _insert_split_docs(conn, table: str, split_docs: list[Document], vectors: list[list[float]]) -> int:
    rows = [
        (
            int(doc.metadata.get("owner_user_id", 0)),
            vec,
            doc.page_content[:8192],
            str(doc.metadata.get("name", ""))[:512],
            str(doc.metadata.get("source", ""))[:1024],
        )
        for doc, vec in zip(split_docs, vectors)
    ]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                f'INSERT INTO "{table}" '
                "(owner_user_id, vector, text, name, source) VALUES (%s, %s, %s, %s, %s)",
                rows,
            )
    return len(rows)


class PgVectorResumeStore:
    """轻量简历向量库封装（原生 SQL + pgvector 扩展，无 ORM）。

    对外暴露 ``similarity_search(query, k)``，与旧版向量库接口一致，
    供 ``rag.retriever.RerankRetriever`` 直接复用。
    """

    def __init__(self, table: str, embeddings):
        self._table = table
        self._embeddings = embeddings

    def similarity_search(self, query: str, k: int = 5,
                          owner_user_id: int | None = None) -> list[Document]:
        if owner_user_id is None:
            raise ValueError("owner_user_id is required for candidate search")
        conn = _get_connection()
        if not _table_exists(conn, self._table):
            return []

        vector = self._embeddings.embed_query(query)
        fetch_k = max(k * 4, k)
        with conn.cursor() as cur:
            # <=> 是 pgvector 的余弦距离操作符；1 - distance 还原成相似度分数。
            cur.execute(
                f"""
                SELECT text, name, source, 1 - (vector <=> %s::vector) AS score
                FROM "{self._table}"
                WHERE owner_user_id = %s
                ORDER BY vector <=> %s::vector
                LIMIT %s
                """,
                (vector, owner_user_id, vector, fetch_k),
            )
            rows = cur.fetchall()

        docs: list[Document] = []
        seen: set[str] = set()
        for text, name, source, score in rows:
            dedupe_key = source or name or text[:80]
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            docs.append(
                Document(
                    page_content=text,
                    metadata={"name": name, "source": source, "score": score},
                )
            )
            if len(docs) >= k:
                break
        return docs


def load_candidate_corpus(owner_user_id: int) -> list[tuple[str, str, str]]:
    """按候选人聚合的语料：一行一个候选人 (source, name, 全部chunk拼接文本)。

    供 ``rag.bm25.BM25Index`` 构建关键词索引使用——索引粒度对齐语义检索侧
    （``PgVectorResumeStore.similarity_search`` 本来就是按候选人去重返回的），
    不需要额外处理"多个 chunk 分数如何聚合成候选人分数"。
    """
    from config import PGVECTOR_TABLE

    conn = _get_connection()
    if not _table_exists(conn, PGVECTOR_TABLE):
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT source, MAX(name), string_agg(text, ' ' ORDER BY id)
            FROM "{PGVECTOR_TABLE}"
            WHERE owner_user_id = %s
            GROUP BY source
            """,
            (owner_user_id,),
        )
        return [(source, name, text) for source, name, text in cur.fetchall()]


RESUME_MANIFEST_NAME = "resume_manifest.json"


def _resume_catalog(resume_dir: str) -> dict:
    """简历目录指纹：用于判断是否需要相对磁盘索引重新建库。"""
    root = Path(resume_dir)
    files: list[dict] = []
    if not root.is_dir():
        return {"v": 1, "files": files}
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() in (".txt", ".pdf"):
            try:
                st = f.stat()
                files.append(
                    {
                        "name": f.name,
                        "mtime": int(st.st_mtime),
                        "size": st.st_size,
                    }
                )
            except OSError:
                continue
    return {"v": 1, "files": files}


def _manifest_path(store_path: str) -> Path:
    return Path(store_path) / RESUME_MANIFEST_NAME


def _read_saved_catalog(store_path: str) -> dict | None:
    mp = _manifest_path(store_path)
    if not mp.is_file():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_resume_manifest(resume_dir: str, store_path: str) -> None:
    Path(store_path).mkdir(parents=True, exist_ok=True)
    catalog = _resume_catalog(resume_dir)
    _manifest_path(store_path).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _invalidate_retriever_cache() -> None:
    try:
        from rag.retriever import invalidate_vector_store_cache

        invalidate_vector_store_cache()
    except Exception:
        pass


def _extract_pdf_text(file: Path) -> str:
    """Extract plain text from a PDF file using pymupdf (better CJK support)."""
    import fitz  # pymupdf

    doc = fitz.open(str(file))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages)


class HashEmbeddings:
    """Deterministic local embeddings for pgvector demos and offline matching.

    OpenRouter is used for chat completion in this project, but it does not
    always expose an embeddings endpoint. This lightweight hashing embedding
    keeps candidate indexing and matching available without another service.
    """

    dimension = 384

    def _tokens(self, text: str) -> list[str]:
        import re

        lower_text = text.lower()
        tokens = re.findall(r"[a-z0-9][a-z0-9+#._-]*", lower_text)
        chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        for run in chinese_runs:
            tokens.extend(run[i : i + 2] for i in range(max(len(run) - 1, 0)))
        return tokens

    def _embed(self, text: str) -> list[float]:
        import hashlib
        import math

        vector = [0.0] * self.dimension
        for token in self._tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _get_embeddings():
    """Return the embedding model instance (OpenAI-compatible API).

    显式传 timeout：不传的话 langchain_openai 会落到 OpenAI SDK 的默认值
    （600 秒），一次几百字的文本转向量调用完全不需要那么长的预算，一旦供应商
    网络抖动，没有这个显式超时会把整条 /api/recruit 请求拖住到 10 分钟。
    """
    from config import EMBEDDING_API_KEY, EMBEDDING_BACKEND, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_TIMEOUT

    if EMBEDDING_BACKEND.lower() in {"hash", "local", "builtin"}:
        return HashEmbeddings()

    from langchain_openai import OpenAIEmbeddings

    kwargs: dict = {"model": EMBEDDING_MODEL, "api_key": EMBEDDING_API_KEY, "timeout": EMBEDDING_TIMEOUT}
    if EMBEDDING_BASE_URL:
        kwargs["base_url"] = EMBEDDING_BASE_URL
        kwargs["default_headers"] = {
            "HTTP-Referer": "https://github.com/recruitment-agent",
        }
    return OpenAIEmbeddings(**kwargs)


def delete_resume_document(owner_user_id: int, source: str) -> int:
    """Delete all vector chunks for a candidate identified by *source*.

    Returns the number of rows deleted (0 if the source was not indexed).
    """
    from config import PGVECTOR_TABLE

    if not source or not source.strip():
        return 0

    safe_source = source.strip()
    conn = _get_connection()
    if not _table_exists(conn, PGVECTOR_TABLE):
        return 0

    with conn.cursor() as cur:
        cur.execute(
            f'DELETE FROM "{PGVECTOR_TABLE}" WHERE owner_user_id = %s AND source = %s',
            (owner_user_id, safe_source[:1024]),
        )
        deleted = cur.rowcount

    _invalidate_retriever_cache()
    print(f"[VectorStore] 已从 pgvector 删除候选人向量，source={safe_source!r}，共 {deleted} 行", flush=True)
    return deleted


def sync_vector_ownership(mappings: list[tuple[int, str]]) -> int:
    """Assign owners to legacy rows by their Java candidate source path."""
    from config import PGVECTOR_TABLE

    if not mappings:
        return 0
    conn = _get_connection()
    if not _table_exists(conn, PGVECTOR_TABLE):
        return 0
    # Existing installations gain the ownership column here even before the
    # next insert/query initializes it through _ensure_resume_table.
    with conn.cursor() as cur:
        cur.execute(
            f'ALTER TABLE "{PGVECTOR_TABLE}" '
            "ADD COLUMN IF NOT EXISTS owner_user_id BIGINT NOT NULL DEFAULT 0"
        )
        updated = 0
        for owner_user_id, source in mappings:
            cur.execute(
                f'UPDATE "{PGVECTOR_TABLE}" SET owner_user_id = %s WHERE source = %s',
                (int(owner_user_id), source[:1024]),
            )
            updated += cur.rowcount
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS "{PGVECTOR_TABLE}_owner_source_idx" '
            f'ON "{PGVECTOR_TABLE}" (owner_user_id, source)'
        )
    _invalidate_retriever_cache()
    return updated


def upsert_resume_document(owner_user_id: int, name: str, source: str, text: str,
                           store_path: str | None = None) -> int:
    """Insert or replace one candidate resume document in pgvector."""
    from config import PGVECTOR_TABLE, RESUME_DIR, VECTOR_STORE_PATH

    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("candidate resume text is empty")

    safe_name = (name or "候选人").strip()
    safe_source = (source or f"candidate:{safe_name}").strip()
    doc = Document(
        page_content=clean_text,
        metadata={
            "owner_user_id": int(owner_user_id),
            "name": safe_name,
            "source": safe_source,
        },
    )
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    split_docs = splitter.split_documents([doc])

    embeddings = _get_embeddings()
    vectors = embeddings.embed_documents([d.page_content for d in split_docs])
    if not vectors:
        raise ValueError("candidate resume text produced no vector chunks")

    conn = _get_connection()
    _ensure_resume_table(conn, PGVECTOR_TABLE, len(vectors[0]))
    _delete_existing_source(conn, PGVECTOR_TABLE, int(owner_user_id), safe_source)
    inserted = _insert_split_docs(conn, PGVECTOR_TABLE, split_docs, vectors)

    _write_resume_manifest(RESUME_DIR, store_path or VECTOR_STORE_PATH)
    _invalidate_retriever_cache()
    print(f"[VectorStore] 已同步候选人 {safe_name} 到 pgvector，共 {inserted} 个文本块", flush=True)
    return inserted


def _load_resume_documents(resume_dir: str) -> list[Document]:
    """Load all .txt and .pdf resume files from the resume directory."""
    docs = []
    resume_path = Path(resume_dir)
    if not resume_path.exists():
        return docs

    for file in sorted(resume_path.iterdir()):
        if file.suffix.lower() == ".txt":
            text = file.read_text(encoding="utf-8")
        elif file.suffix.lower() == ".pdf":
            text = _extract_pdf_text(file)
        else:
            continue

        if not text.strip():
            print(f"[VectorStore] 警告：{file.name} 内容为空，已跳过")
            continue

        candidate_name = file.stem.replace("_", " ").title()
        docs.append(
            Document(
                page_content=text,
                metadata={"name": candidate_name, "source": str(file)},
            )
        )
    return docs


def build_vector_store(resume_dir: str, store_path: str) -> PgVectorResumeStore:
    """Build and persist a pgvector table from resume documents.

    简历目录下的 .txt/.pdf 切块后写入 pgvector 表（全量重建，先 drop 旧表）。
    ``store_path`` 仅用于存放目录指纹 manifest；向量数据存于 Postgres。

    Args:
        resume_dir: Directory containing .txt / .pdf resume files
        store_path: Path to store the resume manifest (rebuild fingerprint)

    Returns:
        PgVectorResumeStore wrapper instance
    """
    from config import PGVECTOR_TABLE

    docs = _load_resume_documents(resume_dir)
    if not docs:
        raise ValueError(f"No resume .txt or .pdf files found in: {resume_dir}")

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    split_docs = splitter.split_documents(docs)

    print("[VectorStore] 正在加载 Embedding 模型并写入 pgvector...")
    embeddings = _get_embeddings()
    vectors = embeddings.embed_documents([d.page_content for d in split_docs])
    dim = len(vectors[0])

    conn = _get_connection()
    _ensure_resume_table(conn, PGVECTOR_TABLE, dim, recreate=True)
    _insert_split_docs(conn, PGVECTOR_TABLE, split_docs, vectors)

    _write_resume_manifest(resume_dir, store_path)
    _invalidate_retriever_cache()
    print(f"[VectorStore] 构建完成，共 {len(split_docs)} 个文本块，已写入 pgvector 表 {PGVECTOR_TABLE}")
    return PgVectorResumeStore(PGVECTOR_TABLE, embeddings)


def load_vector_store(store_path: str | None = None) -> PgVectorResumeStore:
    """Load an existing pgvector table (embeds only at query time).

    Args:
        store_path: 未使用，保留以兼容旧签名

    Returns:
        PgVectorResumeStore wrapper instance
    """
    from config import PGVECTOR_TABLE

    return PgVectorResumeStore(PGVECTOR_TABLE, _get_embeddings())


def get_or_build_vector_store(resume_dir: str, store_path: str) -> PgVectorResumeStore:
    """加载已有 pgvector 表；不存在则全量构建。

    当 ``config.VECTOR_INDEX_AUTO_REBUILD`` 为真时：若表已存在但简历目录相对
    ``resume_manifest.json`` 有变化（增删改、替换），则自动重建并刷新检索缓存。
    """
    from config import PGVECTOR_TABLE, VECTOR_INDEX_AUTO_REBUILD

    conn = _get_connection()
    if not _table_exists(conn, PGVECTOR_TABLE):
        return build_vector_store(resume_dir, store_path)

    if VECTOR_INDEX_AUTO_REBUILD:
        current = _resume_catalog(resume_dir)
        saved = _read_saved_catalog(store_path)
        if saved != current:
            print(
                "[VectorStore] 检测到简历目录与已保存索引不一致，自动重建向量索引…",
                flush=True,
            )
            return build_vector_store(resume_dir, store_path)

    return load_vector_store(store_path)
