"""导入一份真实课件，运行 Agent，并生成评测与裸模型对比记录。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import build_note
from app.core.config import settings
from app.core.security import hash_password
from app.db import repo_business as repo
from app.db.conn import business_db, init_databases
from app.services.ingest import ingest_document
from app.services.llm import get_llm
from scripts.bench_compare import bare_result
from scripts.eval_agent import evaluate_result, load_reference


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material", type=Path, required=True)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--course-name", default="软件工程 第13章 构件级设计")
    parser.add_argument("--output", type=Path,
                        default=settings.storage_dir / "eval" / "compare.json")
    args = parser.parse_args()
    material = args.material.resolve()
    reference_path = args.reference_csv.resolve()
    if not material.exists() or not reference_path.exists():
        raise SystemExit("课件或参考知识点清单不存在")

    init_databases(reset=False)
    with business_db() as conn:
        user = repo.get_user_by_username(conn, "agent_eval")
        user_id = int(user["user_id"]) if user else repo.create_user(
            conn, "agent_eval", hash_password("local-evaluation-only"), "Agent评测账号")
        print("[1/5] 解析并导入真实课件", flush=True)
        ingested = ingest_document(conn, material, user_id=user_id,
                                   course_name=args.course_name,
                                   stored_path=str(material), display_name=material.name)
        if ingested["parse_status"] == "failed":
            raise SystemExit(f"课件解析失败：{ingested}")
        doc_id = int(ingested["doc_id"])
        print(f"      doc_id={doc_id}, chunks={ingested['chunks']}, pages={ingested['page_count']}",
              flush=True)

        print("[2/5] 创建整理任务", flush=True)
        session_id = repo.create_session(conn, user_id=user_id, course_name=args.course_name,
                                         source_file=material.name, doc_ids=[doc_id])
        print(f"      session_id={session_id}", flush=True)

        print("[3/5] 运行定制 Agent 管线", flush=True)
        custom = build_note(conn, session_id)
        print(f"      chapters={len(custom.outline)}, items="
              f"{sum(len(n.items) for n in custom.outline)}, dropped={custom.dropped_items}",
              flush=True)

        reference = load_reference(reference_path)
        print("[4/5] 计算覆盖率与无依据率", flush=True)
        custom_metrics = evaluate_result(custom, reference)
        print(f"      coverage={custom_metrics['knowledge_coverage']:.1%}, "
              f"unsupported={custom_metrics['unsupported_ratio']:.1%}", flush=True)

        print("[5/5] 运行同模型裸调用对比", flush=True)
        chunks = conn.execute(
            "SELECT chunk_key, text, chapter_title, section_title, page_num, slide_index "
            "FROM chunks WHERE doc_id = ? ORDER BY seq", (doc_id,)).fetchall()
        bare = bare_result(args.course_name, [dict(x) for x in chunks])
        bare_metrics = evaluate_result(bare, reference)

    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "doc_id": doc_id,
        "material": material.name,
        "course_name": args.course_name,
        "model": get_llm().config.model,
        "custom_pipeline": custom_metrics,
        "bare_model": bare_metrics,
        "quality": custom.quality.model_dump() if custom.quality else None,
        "warnings": custom.warnings,
        "llm_usage": get_llm().usage.summary(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8")
    detail = args.output.with_name("latest_result.json")
    detail.write_text(custom.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "detail": str(detail),
                      "session_id": session_id, "custom_coverage": custom_metrics["knowledge_coverage"],
                      "bare_coverage": bare_metrics["knowledge_coverage"],
                      "usage": record["llm_usage"]}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
