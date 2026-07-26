"""Regression tests for multi-user candidate and Agent-session isolation."""

import sqlite3
import threading
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document


def test_hybrid_retriever_passes_owner_to_semantic_and_keyword_paths(monkeypatch):
    import rag.retriever as retriever_mod

    captured = {}

    class FakeStore:
        def similarity_search(self, query, k, owner_user_id):
            captured["semantic_owner"] = owner_user_id
            return [
                Document(
                    page_content="Python",
                    metadata={"name": "本用户候选人", "source": "own.pdf", "score": 0.9},
                )
            ]

    class FakeBm25:
        def score(self, query):
            captured["keyword_called"] = True
            return {"own.pdf": 2.0}

        def get_text(self, source):
            return "Python"

        def get_name(self, source):
            return "本用户候选人"

    monkeypatch.setattr(retriever_mod, "_get_vector_store", lambda: FakeStore())
    monkeypatch.setattr(
        retriever_mod,
        "_get_bm25_index",
        lambda owner_user_id: (
            captured.update(keyword_owner=owner_user_id) or FakeBm25()
        ),
    )

    docs = retriever_mod.HybridRetriever(owner_user_id=73, top_k=5).invoke("Python")

    assert [doc.metadata["source"] for doc in docs] == ["own.pdf"]
    assert captured["semantic_owner"] == 73
    assert captured["keyword_owner"] == 73
    assert captured["keyword_called"] is True


def test_refine_session_rejects_different_owner_before_invoking_graph(monkeypatch):
    import main as main_mod

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE session_activity (
            thread_id TEXT PRIMARY KEY,
            owner_user_id INTEGER,
            last_active_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO session_activity VALUES (?, ?, ?)",
        ("session-a", 10, "2026-01-01T00:00:00+00:00"),
    )

    class FakeGraph:
        def get_state(self, config):
            return SimpleNamespace(values={"owner_user_id": 10})

        def invoke(self, state, config):
            raise AssertionError("越权请求不应执行 Agent")

    monkeypatch.setattr(main_mod, "_checkpoint_conn", conn)
    monkeypatch.setattr(main_mod, "_activity_lock", threading.Lock())
    monkeypatch.setattr(main_mod, "recruitment_graph", FakeGraph())

    with pytest.raises(main_mod.SessionAccessDeniedError):
        main_mod.refine_session("session-a", "继续", owner_user_id=11)


def test_internal_api_rejects_missing_and_wrong_service_token():
    from fastapi.testclient import TestClient

    from api.server import app

    client = TestClient(app)
    payload = {"text": "张三 Python 工程师"}
    assert client.post("/api/internal/parse-resume", json=payload).status_code == 401
    assert client.post(
        "/api/internal/parse-resume",
        json=payload,
        headers={"X-Internal-Token": "wrong-token"},
    ).status_code == 401


def test_embedding_dimension_change_never_silently_drops_all_users(monkeypatch):
    import rag.vector_store as vector_store

    monkeypatch.setattr(vector_store, "_table_exists", lambda conn, table: True)
    monkeypatch.setattr(vector_store, "_table_dim", lambda conn, table: 1536)

    with pytest.raises(RuntimeError, match="避免自动删除全部用户"):
        vector_store._ensure_resume_table(object(), "resume_vectors", 3072)
