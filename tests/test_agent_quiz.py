"""Agent 出题的单元测试：结构校验、证据绑定、降级行为。

不调用真实模型：用 monkeypatch 替换 get_llm 与 llm_available，
只验证「模型返回什么 → 我们收下什么」这层逻辑，这几条最容易出错。

覆盖：
    1. 合法题目被收下，且去掉模型自带的「A.」前缀；
    2. answer 越界（E）、选项不足、缺题干 → 丢弃；
    3. evidence_chunk_key 不在给定材料里 → 按知识点名回查补上；查不到则丢弃；
    4. 模型不可用 / 全不合格 → 抛 QuizUnavailable（由上层退化为模板题）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import quiz as agent_quiz  # noqa: E402

KP = [
    {"name": "等价类划分", "definition": "把输入域划分为若干等价类", "chunk_key": "d1-p12-c2", "page": 12},
    {"name": "边界值分析", "definition": "关注输入范围的边界", "chunk_key": "d1-p14-c1", "page": 14},
]


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def json_call(self, system, user, *, default=None, temperature=None):
        return self.payload


@pytest.fixture()
def fake_model(monkeypatch):
    """把 llm_available 置真，并把 get_llm 换成可控的假客户端。"""
    monkeypatch.setattr("app.agents.pipeline.llm_available", lambda: True)

    def _install(payload):
        monkeypatch.setattr("app.services.llm.get_llm", lambda: FakeLLM(payload))

    return _install


def test_accepts_valid_item_and_strips_option_prefix(fake_model) -> None:
    fake_model({"items": [{
        "knowledge_name": "等价类划分",
        "stem": "关于等价类划分，下列说法正确的是？",
        "options": ["A. 把输入域划分为等价类并取代表值", "B. 只测边界", "C. 只测语句覆盖", "D. 只测模块接口"],
        "answer": "a",
        "analysis": "等价类划分关注输入域分类。",
        "evidence_chunk_key": "d1-p12-c2",
        "evidence_page": 12,
    }]})

    items = agent_quiz.generate_quiz_items(None, session_id=1, knowledge_points=KP, count=1)
    assert len(items) == 1
    item = items[0]
    assert item["answer"] == "A"
    assert item["options"][0] == "把输入域划分为等价类并取代表值", "应去掉模型自带的 A. 前缀"
    assert item["evidence_chunk_key"] == "d1-p12-c2"


def test_drops_bad_items(fake_model) -> None:
    fake_model({"items": [
        {"stem": "题干", "options": ["x", "y"], "answer": "E", "evidence_chunk_key": "d1-p12-c2"},
        {"stem": "", "options": ["x", "y"], "answer": "A", "evidence_chunk_key": "d1-p12-c2"},
        {"stem": "题干", "options": ["x"], "answer": "A", "evidence_chunk_key": "d1-p12-c2"},
        {
            "knowledge_name": "不存在的知识点",
            "stem": "题干",
            "options": ["x", "y", "z", "w"],
            "answer": "A",
            "evidence_chunk_key": "fake-key",
        },
    ]})
    with pytest.raises(agent_quiz.QuizUnavailable):
        agent_quiz.generate_quiz_items(None, session_id=1, knowledge_points=KP, count=4)


def test_repairs_evidence_by_knowledge_name(fake_model) -> None:
    fake_model({"items": [{
        "knowledge_name": "边界值分析",
        "stem": "关于边界值分析，下列说法正确的是？",
        "options": ["A 关注输入边界", "B 关注语句覆盖", "C 只做等价分类", "D 不做用例设计"],
        "answer": "A",
        "analysis": "边界附近最容易出缺陷。",
        "evidence_chunk_key": "模型编的 key",
        "evidence_page": None,
    }]})

    items = agent_quiz.generate_quiz_items(None, session_id=1, knowledge_points=KP, count=1)
    assert items[0]["evidence_chunk_key"] == "d1-p14-c1", "应按知识点名回查到真实出处"
    assert items[0]["evidence_page"] == 14


def test_unavailable_when_no_key(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.pipeline.llm_available", lambda: False)
    with pytest.raises(agent_quiz.QuizUnavailable):
        agent_quiz.generate_quiz_items(None, session_id=1, knowledge_points=KP, count=3)


def test_unavailable_when_model_raises(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.pipeline.llm_available", lambda: True)

    class Boom:
        def json_call(self, *a, **kw):
            raise RuntimeError("网络超时")

    monkeypatch.setattr("app.services.llm.get_llm", lambda: Boom())
    with pytest.raises(agent_quiz.QuizUnavailable):
        agent_quiz.generate_quiz_items(None, session_id=1, knowledge_points=KP, count=1)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
