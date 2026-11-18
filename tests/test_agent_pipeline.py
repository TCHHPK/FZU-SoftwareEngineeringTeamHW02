from __future__ import annotations

from app.agents import pipeline
from app.schemas.agent_io import Evidence, KnowledgeItem, NoteResult, OutlineNode
from scripts.eval_agent import evaluate_result


class DummyProgress:
    def __init__(self):
        self.events = []

    def report(self, progress, message):
        self.events.append((progress, message))


class FakeLLM:
    def json_call(self, system, user, **kwargs):
        if "知识抽取器" in system:
            return {"items": [
                {"name": "构件定义", "definition": "构件是可部署单元",
                 "key_points": ["封装实现"], "importance": 5,
                 "quote": "构件是可部署单元，封装实现并通过接口提供服务。"},
                {"name": "无依据内容", "definition": "编造",
                 "quote": "原文中不存在的句子"},
            ]}
        if "课程笔记编辑器" in system:
            return {"chapter_summaries": [{"title": "第13章", "summary": "构件级设计"}],
                    "key_points": ["构件定义"],
                    "mindmap_text": "课程\n└─ 第13章\n   └─ 构件定义"}
        if "质量审核器" in system:
            return {"core": 90, "structure": 85, "extension": 70,
                    "reasons": ["跨章节关联较少"]}
        return kwargs.get("default")


def test_real_pipeline_filters_unverifiable_items(monkeypatch):
    monkeypatch.setattr(pipeline, "get_llm", lambda: FakeLLM())
    # 必须同时屏蔽「有没有密钥」这项检查：
    # 否则这条用例会隐式依赖运行者本机 .env 里恰好有真实密钥——
    # 在别人机器上跑就会抛 PipelineNotConfigured，属于测试自身的环境泄漏。
    monkeypatch.setattr(pipeline, "llm_available", lambda: True)
    monkeypatch.setattr(pipeline, "_supplement_from_retrieval", lambda *_args: None)
    monkeypatch.setattr(pipeline.settings, "enable_quality_eval", True)
    chunks = [{
        "chunk_key": "d1-p2-c1",
        "text": "构件是可部署单元，封装实现并通过接口提供服务。",
        "source_file": "chapter13.pdf",
        "chapter_title": "第13章",
        "section_title": "构件",
        "page_num": 2,
        "slide_index": None,
    }]
    progress = DummyProgress()
    result = pipeline.run_note_pipeline(
        None, {"user_id": 1, "course_name": "软件工程", "doc_ids": [1]}, chunks,
        progress=progress)

    assert result.dropped_items == 1
    assert len(result.outline) == 1
    assert len(result.outline[0].items) == 1
    item = result.outline[0].items[0]
    assert item.verified is True
    assert item.evidence[0].chunk_key == "d1-p2-c1"
    assert result.quality and result.quality.total == 88.5
    assert progress.events[-1][0] == 94


def test_deduplicate_merges_points_and_evidence():
    first = pipeline._bind_extracted_item(
        {"name": "构件 定义", "definition": "短定义", "key_points": ["A"],
         "quote": "构件是可部署单元"},
        {"chunk_key": "a", "text": "构件是可部署单元", "chapter_title": "章"})
    second = pipeline._bind_extracted_item(
        {"name": "构件定义", "definition": "这是更完整的定义", "key_points": ["B"],
         "quote": "构件通过接口提供服务"},
        {"chunk_key": "b", "text": "构件通过接口提供服务", "chapter_title": "章"})
    merged = pipeline._deduplicate_items([first, second])
    assert len(merged) == 1
    assert merged[0].definition == "这是更完整的定义"
    assert merged[0].key_points == ["A", "B"]
    assert {e.chunk_key for e in merged[0].evidence} == {"a", "b"}


def test_evaluation_reports_coverage_and_unsupported_ratio():
    verified = KnowledgeItem(
        name="构件与对象的区别", key_points=["构件是可部署单元"], verified=True,
        evidence=[Evidence(chunk_key="d1-p1-c1", quote="构件是可部署单元")])
    unsupported = KnowledgeItem(name="额外编造内容", verified=False)
    result = NoteResult(outline=[OutlineNode(title="第13章", items=[verified, unsupported])])
    reference = [{"知识点名称": "构件与对象的区别", "核心要点": "构件是可部署单元"}]
    metrics = evaluate_result(result, reference)
    assert metrics["knowledge_coverage"] == 1.0
    assert metrics["unsupported_ratio"] == 0.5
