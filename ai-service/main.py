"""LangGraph workflow definition and entry points for the recruitment agent."""

import os
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import StateGraph, START, END

from agent.schemas import AgentState
from agent.observability import reset_run_metrics, get_run_metrics
from agent.agent import agent_node, tool_executor_node, compress_node, route_from_agent
from config import AGENT_RECURSION_LIMIT, CHECKPOINT_DB_PATH, SESSION_TTL_DAYS


class SessionNotFoundError(Exception):
    """Raised when refine_session is called with an unknown session_id."""


class SessionAccessDeniedError(Exception):
    """Raised when a user tries to continue another user's session."""


class AgentLoopLimitError(Exception):
    """Raised when an Agent run exceeds the configured LangGraph step budget."""


def _graph_config(session_id: str) -> dict:
    """Build one consistent graph config for new and continued sessions."""
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": AGENT_RECURSION_LIMIT,
    }


def _invoke_recruitment_graph(input_state: dict, config: dict) -> dict:
    """Invoke the graph and convert its framework error into a stable app error."""
    try:
        return recruitment_graph.invoke(input_state, config)
    except GraphRecursionError as exc:
        raise AgentLoopLimitError(
            f"Agent execution exceeded {AGENT_RECURSION_LIMIT} steps"
        ) from exc


# ── 会话持久化（SqliteSaver）────────────────────────────────────────────────
#
# 用 SQLite 文件持久化 Agent 会话状态，替代重启即丢的 MemorySaver：
# 1. 进程重启后，正在进行中的"优化结果"多轮反馈不会失效；
# 2. 配合下面的 session_activity 表 + cleanup_expired_sessions()，避免内存/磁盘
#    随着历史会话数量无限增长（MemorySaver 从不清理旧会话，是一个真实的内存泄漏）。
#
# SqliteSaver 官方文档明确"面向轻量单进程场景，不支持多线程扩展"——这与本项目
# ai-service 单实例部署的现状匹配；如果以后要多副本水平扩展，需要换成
# PostgresSaver（复用现有 pgvector 实例），届时只需替换这里的 checkpointer 实例。
Path(CHECKPOINT_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
_checkpoint_conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
_activity_lock = threading.Lock()


def _init_session_activity_table() -> None:
    """建一张独立的"会话活跃时间"表，供 TTL 清理使用。

    不从 SqliteSaver 自己的 checkpoints 表里解析时间戳——那张表的 schema 是
    LangGraph 内部实现细节，不应该依赖；单独维护一张小表，语义更清晰、
    也不会因为 LangGraph 版本升级改了内部 schema 而失效。
    """
    with _activity_lock:
        _checkpoint_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_activity (
                thread_id TEXT PRIMARY KEY,
                owner_user_id INTEGER,
                last_active_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1] for row in _checkpoint_conn.execute(
                "PRAGMA table_info(session_activity)"
            ).fetchall()
        }
        if "owner_user_id" not in columns:
            _checkpoint_conn.execute(
                "ALTER TABLE session_activity ADD COLUMN owner_user_id INTEGER"
            )
        _checkpoint_conn.commit()


def _touch_session(session_id: str, owner_user_id: int) -> None:
    """记录/刷新一次会话的最近活跃时间。在每次 start_session/refine_session 时调用。"""
    with _activity_lock:
        _checkpoint_conn.execute(
            """
            INSERT INTO session_activity (thread_id, owner_user_id, last_active_at)
            VALUES (?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET last_active_at = excluded.last_active_at
            """,
            (session_id, owner_user_id, datetime.now(timezone.utc).isoformat()),
        )
        _checkpoint_conn.commit()


def cleanup_expired_sessions(days: int = SESSION_TTL_DAYS) -> int:
    """删除超过 ``days`` 天没有新消息的会话（checkpoint 数据 + 活跃时间记录）。

    供 API 服务启动时调用一次（见 api/server.py 的 startup 事件）。返回本次清理的会话数。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _activity_lock:
        cur = _checkpoint_conn.execute(
            "SELECT thread_id FROM session_activity WHERE last_active_at < ?", (cutoff,)
        )
        expired_ids = [row[0] for row in cur.fetchall()]

    for thread_id in expired_ids:
        checkpointer.delete_thread(thread_id)
        with _activity_lock:
            _checkpoint_conn.execute("DELETE FROM session_activity WHERE thread_id = ?", (thread_id,))
            _checkpoint_conn.commit()

    if expired_ids:
        print(f"[Checkpoint] 已清理 {len(expired_ids)} 个超过 {days} 天未活跃的会话", flush=True)
    return len(expired_ids)


_init_session_activity_table()
checkpointer = SqliteSaver(_checkpoint_conn)


def build_graph():
    """Build and compile the single-agent ReAct workflow graph."""
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_executor_node)
    # compress 卡在"agent 决定不再调用工具"和"真正结束"之间：一轮 ReAct 循环
    # 结束时，按 HumanMessage 边界保留最近若干个完整轮次，避免长期反馈让模型
    # 上下文和 checkpoint 消息历史无限增长。
    builder.add_node("compress", compress_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route_from_agent, {"tools": "tools", "__end__": "compress"})
    builder.add_edge("tools", "agent")
    builder.add_edge("compress", END)

    return builder.compile(checkpointer=checkpointer)


recruitment_graph = build_graph()


def start_session(session_id: str, message: str, top_k: int = 5,
                  owner_user_id: int | None = None) -> dict:
    """Start a brand-new matching session under the given session_id."""
    if owner_user_id is None:
        raise ValueError("owner_user_id is required")
    reset_run_metrics()
    _touch_session(session_id, owner_user_id)
    config = _graph_config(session_id)
    return _invoke_recruitment_graph(
        {
            "session_id": session_id,
            "owner_user_id": owner_user_id,
            "match_top_k": max(1, min(30, int(top_k or 5))),
            "jd_info": None,
            "candidates": [],
            "match_results": [],
            "completion_guard_retries": 0,
            "messages": [HumanMessage(content=message)],
        },
        config,
    )


def get_session_snapshot(session_id: str, owner_user_id: int | None = None) -> dict:
    """Return authoritative session state after applying the same owner checks as refine."""
    if owner_user_id is None:
        raise ValueError("owner_user_id is required")
    config = _graph_config(session_id)
    existing = recruitment_graph.get_state(config)
    if not existing.values:
        raise SessionNotFoundError(session_id)
    if existing.values.get("owner_user_id") != owner_user_id:
        raise SessionAccessDeniedError(session_id)
    with _activity_lock:
        row = _checkpoint_conn.execute(
            "SELECT owner_user_id FROM session_activity WHERE thread_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_id)
    if row[0] != owner_user_id:
        raise SessionAccessDeniedError(session_id)
    _touch_session(session_id, owner_user_id)
    return dict(existing.values)


def refine_session(session_id: str, message: str,
                   owner_user_id: int | None = None) -> dict:
    """Continue an existing session with additional user feedback."""
    config = _graph_config(session_id)
    get_session_snapshot(session_id, owner_user_id)
    # 不清空 candidates/match_results：如果这一轮反馈 Agent 判断"不需要重新
    # 打分，直接基于已有结果回答"（如"帮我总结一下前三名"），前端应继续展示
    # 上一轮的候选人列表，清空会导致返回空列表。真正需要重新打分同一批候选人
    # 时（如"排除某学历"），去重逻辑已经在 agent.py::tool_executor_node 里按
    # 简历路径识别"这是同一个人"并直接覆盖旧条目，不会再出现旧结果同时和新
    # 结果一起显示（"曼巴（2）"）的问题。
    return _invoke_recruitment_graph(
        {
            "completion_guard_retries": 0,
            "messages": [HumanMessage(content=message)],
        },
        config,
    )


if __name__ == "__main__":
    from uuid import uuid4

    user_input = input("请输入招生需求（例如：招收多模态大模型方向硕士研究生）：\n> ").strip()
    result = start_session(uuid4().hex, user_input, owner_user_id=1)

    metrics = get_run_metrics()
    final_message = result["messages"][-1]
    print("\n" + "=" * 60)
    print("📊 最终回复：")
    print("=" * 60)
    print(final_message.content if hasattr(final_message, "content") else final_message)
    print("\n" + "-" * 60)
    print(f"📈 运行指标: {metrics}")
