"""在同一模型、同一课件上比较裸调用与定制 Agent 管线。

该脚本会真实调用模型并消耗额度。先创建整理任务，再运行：
  python scripts/bench_compare.py --session-id 1 --reference-csv reference.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import ProgressReporter, _doc_chunks, run_note_pipeline
from app.core.config import settings
from app.db import repo_business as repo
from app.db.conn import business_db
from app.schemas.agent_io import KnowledgeItem, NoteResult, OutlineNode
from app.services.llm import get_llm
from scripts.eval_agent import evaluate_result, load_reference, result_from_session


BARE_SYSTEM = """你是课程笔记助手。请直接根据课件原文生成知识点列表。
返回严格 JSON：{"items":[{"name":"名称","definition":"定义","key_points":["要点"]}]}。
不得使用输入之外的资料。"""


def bare_result(course_name: str, chunks: list[dict]) -> NoteResult:
    # 控制单次输入规模，避免超过模型上下文；裸调用与定制管线使用相同原始材料顺序。
    text = "\n\n".join(str(c.get("text") or "") for c in chunks)[:60000]
    raw = get_llm().json_call(BARE_SYSTEM, text, default={"items": []})
    items = []
    for row in raw.get("items", []) if isinstance(raw, dict) else []:
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            continue
        items.append(KnowledgeItem(name=str(row["name"]),
                                   definition=str(row.get("definition") or ""),
                                   key_points=[str(x) for x in row.get("key_points", [])],
                                   verified=False, evidence=[]))
    return NoteResult(course_name=course_name,
                      outline=[OutlineNode(title=course_name or "裸模型结果", items=items)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=settings.storage_dir / "eval" / "bench.json")
    parser.add_argument("--rerun-custom", action="store_true",
                        help="重新运行定制管线；默认复用该任务已经落库的结果以节省额度")
    args = parser.parse_args()
    reference = load_reference(args.reference_csv)

    with business_db() as conn:
        session = repo.get_session(conn, args.session_id)
        if not session:
            raise SystemExit(f"任务不存在：{args.session_id}")
        chunks = [chunk for doc_id in session["doc_ids"] for chunk in _doc_chunks(conn, doc_id)]
        if not chunks:
            raise SystemExit("任务没有可用课件分块")
        bare = bare_result(session["course_name"], chunks)
        custom = result_from_session(conn, args.session_id)
        if args.rerun_custom or not custom.outline:
            custom = run_note_pipeline(conn, session, chunks,
                                       progress=ProgressReporter(conn, args.session_id))

    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": args.session_id,
        "course_name": session["course_name"],
        "model": get_llm().config.model,
        "bare_model": evaluate_result(bare, reference),
        "custom_pipeline": evaluate_result(custom, reference),
        "llm_usage": get_llm().usage.summary(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
