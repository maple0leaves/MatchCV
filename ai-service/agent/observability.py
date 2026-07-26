"""Structured observability helpers for the recruitment agent.

All functions degrade gracefully when LangSmith is not configured — they
still collect local metrics and log to stderr so nothing breaks in dev.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("recruitment.observability")

try:
    from langsmith import traceable as _ls_traceable
    from langsmith.run_helpers import get_current_run_tree

    _HAS_LANGSMITH = True
except ImportError:
    _HAS_LANGSMITH = False

    def _ls_traceable(*args: Any, **kwargs: Any) -> Callable:  # type: ignore[misc]
        """No-op fallback when langsmith is not installed."""

        def decorator(fn: Callable) -> Callable:
            return fn

        if args and callable(args[0]):
            return args[0]
        return decorator

    def get_current_run_tree() -> None:  # type: ignore[misc]
        return None


class _RunMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.tool_calls: int = 0
            self.rag_retrievals: int = 0
            self.total_latency_ms: float = 0.0
            self.start_time: float = time.monotonic()

    def record_tool_call(self, latency_ms: float) -> None:
        with self._lock:
            self.tool_calls += 1
            self.total_latency_ms += latency_ms

    def record_rag_retrieval(self) -> None:
        with self._lock:
            self.rag_retrievals += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = (time.monotonic() - self.start_time) * 1000
            return {
                "tool_calls": self.tool_calls,
                "rag_retrievals": self.rag_retrievals,
                "total_tool_latency_ms": round(self.total_latency_ms, 2),
                "wall_time_ms": round(elapsed, 2),
            }


_metrics = _RunMetrics()


def trace_agent_step(node_name: str) -> Callable:
    """Decorator that wraps a graph node function with LangSmith tracing."""

    def decorator(fn: Callable) -> Callable:
        @_ls_traceable(name=node_name, metadata={"graph_node": node_name})
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.monotonic()
            logger.info("node=%s started", node_name)
            result = fn(*args, **kwargs)
            elapsed_ms = (time.monotonic() - t0) * 1000

            run_tree = get_current_run_tree() if _HAS_LANGSMITH else None
            if run_tree is not None:
                run_tree.metadata = {
                    **(run_tree.metadata or {}),
                    "node_latency_ms": round(elapsed_ms, 2),
                }

            logger.info("node=%s finished in %.1fms", node_name, elapsed_ms)
            return result

        return wrapper

    return decorator


def log_tool_usage(
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    latency_ms: float,
) -> None:
    """Record a single tool invocation for metrics and LangSmith metadata."""
    _metrics.record_tool_call(latency_ms)

    run_tree = get_current_run_tree() if _HAS_LANGSMITH else None
    if run_tree is not None:
        events = run_tree.metadata.get("tool_events", []) if run_tree.metadata else []
        events.append(
            {
                "tool": tool_name,
                "latency_ms": round(latency_ms, 2),
                "args_keys": list(args.keys()),
            }
        )
        run_tree.metadata = {**(run_tree.metadata or {}), "tool_events": events}

    logger.info(
        "tool=%s latency=%.1fms args_keys=%s",
        tool_name,
        latency_ms,
        list(args.keys()),
    )


def log_rag_retrieval(
    query: str,
    docs_count: int,
    reranked: bool = False,
) -> None:
    """Record a RAG retrieval event."""
    _metrics.record_rag_retrieval()

    run_tree = get_current_run_tree() if _HAS_LANGSMITH else None
    if run_tree is not None:
        run_tree.metadata = {
            **(run_tree.metadata or {}),
            "last_rag_query": query[:200],
            "last_rag_docs_count": docs_count,
            "last_rag_reranked": reranked,
        }

    logger.info(
        "rag query=%r docs=%d reranked=%s",
        query[:80],
        docs_count,
        reranked,
    )


def get_run_metrics() -> dict[str, Any]:
    """Return a snapshot of aggregated metrics for the current run."""
    return _metrics.snapshot()


def reset_run_metrics() -> None:
    """Reset the per-run counters."""
    _metrics.reset()
