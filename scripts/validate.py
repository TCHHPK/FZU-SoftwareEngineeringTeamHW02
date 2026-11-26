"""评测数据校验与旧版输入导出；只用标准库，不调用应用、数据库或模型。"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

STATUSES = {"answerable", "insufficient", "not_covered"}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path.name}:{line_no}: 不允许空行")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_no}: JSON 错误: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{line_no}: 每行必须是对象")
        rows.append(row)
    return rows


def required_text(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: 需要非空字符串")


def safe_source(root: Path, relative: str) -> Path:
    required_text(relative, "file")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"材料路径不存在或超出数据目录: {relative}")
    return path


def validate(root: Path) -> dict:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != "1.0":
        raise ValueError("不支持的 schema_version")
    docs = read_jsonl(root / "documents.jsonl")
    cases = read_jsonl(root / "qa.jsonl")
    doc_index = {}
    point_total = 0
    point_ids = set()
    for doc in docs:
        did = doc.get("doc")
        required_text(did, "doc")
        if did in doc_index:
            raise ValueError(f"重复 doc: {did}")
        if doc.get("origin") != "self_authored_fixture":
            raise ValueError(f"{did}: 本数据集只接受明确标注的自编材料")
        path = safe_source(root, doc.get("file"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc.get("sha256"):
            raise ValueError(f"{did}: 源文件 SHA256 不一致")
        pages = {}
        for page in doc.get("pages", []):
            number = page.get("page_num")
            if type(number) is not int or number <= 0 or number in pages:
                raise ValueError(f"{did}: 页码必须为唯一正整数")
            required_text(page.get("title"), f"{did}:page.title")
            required_text(page.get("text"), f"{did}:page.text")
            pages[number] = page["text"]
        if not pages or sorted(pages) != list(range(1, len(pages) + 1)):
            raise ValueError(f"{did}: 页码必须从1连续递增")
        expected_text = "\n\n".join(f"第{p['page_num']}页 {p['title']}\n{p['text']}" for p in doc["pages"]) + "\n"
        if path.with_suffix(".txt").read_text(encoding="utf-8") != expected_text:
            raise ValueError(f"{did}: 纯文本材料与页码标注不一致")
        points = doc.get("knowledge_points")
        if not isinstance(points, list) or not points:
            raise ValueError(f"{did}: 缺少知识点标注")
        for point in points:
            for key in ("id", "name", "core", "quote"):
                required_text(point.get(key), f"{did}:point.{key}")
            if point["id"] in point_ids:
                raise ValueError(f"重复知识点ID: {point['id']}")
            point_ids.add(point["id"])
            if point.get("page_num") not in pages or point["quote"] not in pages[point["page_num"]]:
                raise ValueError(f"{did}: 知识点引文与页码不匹配")
        point_total += len(points)
        doc_index[did] = pages

    ids, questions = set(), set()
    distribution = Counter()
    per_doc = Counter()
    for case in cases:
        for key in ("id", "doc", "question", "reference", "rubric", "category"):
            required_text(case.get(key), f"case.{key}")
        cid, did = case["id"], case["doc"]
        if cid in ids:
            raise ValueError(f"重复题目ID: {cid}")
        ids.add(cid)
        question_key = (did, case["question"].strip())
        if question_key in questions:
            raise ValueError(f"{cid}: 同材料重复问题")
        questions.add(question_key)
        if did not in doc_index:
            raise ValueError(f"{cid}: 未知材料 {did}")
        status = case.get("expected_status")
        if status not in STATUSES:
            raise ValueError(f"{cid}: 非法 expected_status")
        claims, evidence = case.get("reference_claims"), case.get("evidence")
        if not isinstance(claims, list) or not isinstance(evidence, list):
            raise ValueError(f"{cid}: claims/evidence 必须是数组")
        if status == "answerable" and (not claims or not evidence):
            raise ValueError(f"{cid}: 可回答题必须有参考主张及证据")
        if status != "answerable" and claims:
            raise ValueError(f"{cid}: 拒答题不计内容召回分母，claims 应为空")
        if status == "insufficient" and not evidence:
            raise ValueError(f"{cid}: 材料不足题须标注部分依据或范围声明")
        for claim in claims:
            required_text(claim, f"{cid}:claim")
        for e in evidence:
            required_text(e.get("quote"), f"{cid}:quote")
            page = e.get("page_num")
            if type(page) is not int or page not in doc_index[did] or e["quote"] not in doc_index[did][page]:
                raise ValueError(f"{cid}: 证据不属于指定材料页码")
        groups = case.get("expected_keywords")
        if not isinstance(groups, list) or (status == "answerable" and not groups):
            raise ValueError(f"{cid}: 关键词格式错误或为空")
        for group in groups:
            words = group if isinstance(group, list) else [group]
            if not words:
                raise ValueError(f"{cid}: 关键词备选组为空")
            for word in words:
                required_text(word, f"{cid}:keyword")
        per_doc[did] += 1
        distribution[status] += 1
    counts = {"documents": len(docs), "questions": len(cases), "knowledge_points": point_total,
              **{status: distribution[status] for status in sorted(STATUSES)}}
    for key, value in counts.items():
        if manifest.get(key) != value:
            raise ValueError(f"manifest 计数不一致: {key}, actual={value}")
    if set(per_doc) != set(doc_index) or any(n != 4 for n in per_doc.values()):
        raise ValueError("每份课件必须有4题")
    return {"status": "validated", "dataset_version": manifest["dataset_version"], **counts,
            "per_doc": dict(per_doc), "model_called": False, "metrics": None}


def export_legacy(root: Path, target: Path, mapping: dict) -> dict:
    """仅作输入转换，不运行模型。每份材料单独导出参考清单与可答题。"""
    validate(root)
    docs = read_jsonl(root / "documents.jsonl")
    cases = read_jsonl(root / "qa.jsonl")
    required = {d["doc"] for d in docs}
    if set(mapping) != required or any(type(v) is not int or v <= 0 for v in mapping.values()):
        raise ValueError("doc-map 必须完整映射5份材料到实际上传后的正整数 doc_id")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("doc-map 不能把多份材料映射到同一 doc_id")
    target = target.resolve()
    if target == root.resolve() or target.is_relative_to(root.resolve()):
        raise ValueError("导出目录不能位于源数据目录内")
    target.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        did = doc["doc"]
        with (target / f"{did}.reference.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["知识点名称", "核心要点"])
            writer.writeheader()
            writer.writerows({"知识点名称": p["name"], "核心要点": p["core"]} for p in doc["knowledge_points"])
        qa = [{"id": c["id"], "question": c["question"], "expected_keywords": c["expected_keywords"],
               "doc_ids": [mapping[did]]} for c in cases if c["doc"] == did and c["expected_status"] == "answerable"]
        (target / f"{did}.qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    summary = {"status": "exported", "answerable_exported": 15, "refusal_excluded": 5,
               "note": "旧脚本不能判定三态拒答，排除的5题必须由新版脚本测；不能报告20题正确率。", "model_called": False}
    (target / "export-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--export-legacy", type=Path)
    parser.add_argument("--doc-map", type=Path, help="显式提供上传后实际 doc_id，不接受猜测ID")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.cases)
        if args.export_legacy:
            if not args.doc_map:
                raise ValueError("导出旧格式须提供 --doc-map")
            result = export_legacy(args.cases, args.export_legacy, json.loads(args.doc_map.read_text(encoding="utf-8-sig")))
        elif args.doc_map:
            raise ValueError("--doc-map 应与 --export-legacy 一起使用")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"数据校验失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
