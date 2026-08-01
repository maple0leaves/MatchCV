"""Regression tests for concise resume summaries."""

from agent.prompt import RESUME_PARSE_PROMPT
from agent.schemas import StudentProfile
from api.server import _local_parse_resume_text


def test_llm_summary_is_limited_to_three_sentences_and_bounded():
    summary = (
        "第一句概括学历与专业。"
        "第二句概括核心技能与研究方法。"
        "第三句概括最有代表性的项目成果。"
        "第四句开始逐项复述课程、奖项和所有实验指标，不应进入最终摘要。"
    )

    profile = StudentProfile(summary=summary)

    assert profile.summary == (
        "第一句概括学历与专业。"
        "第二句概括核心技能与研究方法。"
        "第三句概括最有代表性的项目成果。"
    )
    assert len(profile.summary) <= 220


def test_single_run_on_summary_has_a_hard_limit():
    profile = StudentProfile(summary="项目经历与技术成果" * 80)

    assert len(profile.summary) <= 220
    assert profile.summary.endswith("…")


def test_local_fallback_builds_a_summary_instead_of_copying_first_eight_lines():
    resume_text = """林若辰
学历：本科 专业：人工智能
核心课程：机器学习（99）、操作系统（92）
项目经历
项目描述：使用 Python 和 MySQL 完成数据清洗、特征工程及随机森林建模，并实现故障概率预测。
技术成果：这里包含大量不应该逐项复制到摘要中的实验指标。
"""

    profile = _local_parse_resume_text(resume_text)

    assert profile.summary.startswith("最高学历为本科；核心技能包括MySQL、Python")
    assert "代表经历为使用 Python 和 MySQL" in profile.summary
    assert "核心课程：" not in profile.summary
    assert "。。" not in profile.summary
    assert len(profile.summary) <= 220


def test_resume_prompt_explicitly_requires_a_real_summary():
    assert "2-3 句话" in RESUME_PARSE_PROMPT
    assert "中文不超过 180 个汉字" in RESUME_PARSE_PROMPT
    assert "不要大段照抄简历原文" in RESUME_PARSE_PROMPT
