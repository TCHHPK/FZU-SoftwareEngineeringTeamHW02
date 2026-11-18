"""评测 Agent 的知识点覆盖率、无依据陈述比例与问答正确率。

示例：
  python scripts/eval_agent.py --session-id 1 --reference-csv "参考知识点清单.csv"
  python scripts/eval_agent.py --result-json result.json --reference-csv reference.csv

可选的问答文件格式：
[{"question":"...", "expected_keywords":["词1","词2"], "doc_ids":[1]}]
不提供问答文件时，问答正确率记为 null，绝不伪造分数。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import answer_question
from app.core.config import settings
from app.db import repo_business as repo
from app.db.conn import business_db
from app.schemas.agent_io import KnowledgeItem, NoteResult, OutlineNode
from app.services.query import query_bigrams


def _norm(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", (text or "").lower())


def _similarity(left: str, right: str) -> float:
    a, b = query_bigrams(left), query_bigrams(right)
    if not a or not b:
        return 1.0 if _norm(left) == _norm(right) and _norm(left) else 0.0
    return len(a & b) / len(a | b)


def load_reference(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("知识点名称") or "").strip()]


def result_from_session(conn, session_id: int) -> NoteResult:
    session = repo.get_session(conn, session_id)
    if not session:
        raise ValueError(f"任务不存在：{session_id}")
    notes = repo.list_notes(conn, session_id)
    outline: list[OutlineNode] = []
    key_points: list[str] = []
    mindmap = ""
    dropped = 0
    quality = None
    for note in notes:
        if note["content_type"] == "note":
            items = [KnowledgeItem.model_validate(x)
                     for x in repo.list_note_items(conn, int(note["note_id"]))]
            outline.append(OutlineNode(title=note.get("chapter_title") or session["course_name"],
                                       items=items))
            dropped += int(note.get("dropped_items") or 0)
        elif note["content_type"] == "key_points":
            key_points.extend(x for x in str(note.get("content") or "").splitlines() if x.strip())
        elif note["content_type"] == "mindmap":
            mindmap = str(note.get("content") or "")
    return NoteResult(course_name=session["course_name"], outline=outline,
                      key_points=key_points, mindmap_text=mindmap,
                      quality=quality, dropped_items=dropped)


def evaluate_result(result: NoteResult, reference: list[dict], *, threshold: float = 0.34) -> dict:
    items = [item for node in result.outline for item in node.items]
    matched: list[dict] = []
    missed: list[str] = []
    for ref in reference:
        name = (ref.get("知识点名称") or "").strip()
        core = (ref.get("核心要点") or "").strip()
        best_name, best_score = "", 0.0
        for item in items:
            score = max(_similarity(name, item.name),
                        0.75 * _similarity(name + core, item.name + " " + " ".join(item.key_points)))
            if score > best_score:
                best_name, best_score = item.name, score
        if best_score >= threshold:
            matched.append({"reference": name, "generated": best_name,
                            "score": round(best_score, 3)})
        else:
            missed.append(name)

    unsupported = [item.name for item in items if not item.verified or not item.evidence]
    return {
        "reference_count": len(reference),
        "generated_count": len(items),
        "matched_count": len(matched),
        "knowledge_coverage": round(len(matched) / max(len(reference), 1), 4),
        "unsupported_count": len(unsupported),
        "unsupported_ratio": round(len(unsupported) / max(len(items), 1), 4),
        "matched": matched,
        "missed": missed,
        "unsupported_items": unsupported,
    }


def evaluate_qa(conn, cases: Iterable[dict], default_doc_ids: list[int]) -> dict:
    details = []
    for case in cases:
        expected_groups = []
        for value in case.get("expected_keywords", []):
            group = value if isinstance(value, list) else [value]
            cleaned = [str(x) for x in group if str(x)]
            if cleaned:
                expected_groups.append(cleaned)
        result = answer_question(conn, question=str(case["question"]),
                                 doc_ids=case.get("doc_ids") or default_doc_ids)
        correct = bool(expected_groups) and all(
            any(word in result.answer for word in group) for group in expected_groups)
        details.append({"question": case["question"], "correct": correct,
                        "insufficient": result.insufficient,
                        "expected_keywords": expected_groups, "answer": result.answer})
    return {"question_count": len(details),
            "correct_count": sum(1 for x in details if x["correct"]),
            "qa_accuracy": (round(sum(1 for x in details if x["correct"]) / len(details), 4)
                            if details else None),
            "details": details}


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session-id", type=int)
    source.add_argument("--result-json", type=Path)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--qa-file", type=Path)
    parser.add_argument("--output", type=Path,
                        default=settings.storage_dir / "eval" / "compare.json")
    parser.add_argument("--threshold", type=float, default=0.34)
    args = parser.parse_args()

    reference = load_reference(args.reference_csv)
    with business_db() as conn:
        if args.session_id is not None:
            result = result_from_session(conn, args.session_id)
            session = repo.get_session(conn, args.session_id) or {}
            doc_ids = session.get("doc_ids") or []
        else:
            result = NoteResult.model_validate_json(args.result_json.read_text(encoding="utf-8"))
            doc_ids = []
        metrics = evaluate_result(result, reference, threshold=args.threshold)
        qa = {"question_count": 0, "correct_count": 0, "qa_accuracy": None, "details": []}
        if args.qa_file:
            qa = evaluate_qa(conn, json.loads(args.qa_file.read_text(encoding="utf-8")), doc_ids)

    record = {"created_at": datetime.now(timezone.utc).isoformat(),
              "course_name": result.course_name, "session_id": args.session_id,
              **metrics, **qa}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
