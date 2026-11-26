"""验证数据损坏与导出边界；不属于业务 pytest 基线数量。"""
import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import export_legacy, read_jsonl, validate


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "cases"
        shutil.copytree(Path(__file__).resolve().parent, self.root,
                        ignore=shutil.ignore_patterns("__pycache__"))

    def mutate(self, name, fn):
        path = self.root / name
        rows = read_jsonl(path)
        fn(rows)
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)+"\n", encoding="utf-8")

    def test_valid_counts_and_no_product_metrics(self):
        result = validate(self.root)
        self.assertEqual((result['documents'], result['questions'], result['answerable']), (5, 20, 15))
        self.assertIsNone(result['metrics'])
        self.assertFalse(result['model_called'])

    def test_reject_duplicate_question_id(self):
        self.mutate('qa.jsonl', lambda rows: rows[1].update(id=rows[0]['id']))
        with self.assertRaisesRegex(ValueError, '重复题目ID'):
            validate(self.root)

    def test_reject_evidence_from_wrong_page(self):
        self.mutate('qa.jsonl', lambda rows: rows[0]['evidence'][0].update(page_num=2))
        with self.assertRaisesRegex(ValueError, '证据不属于'):
            validate(self.root)

    def test_reject_missing_claims_for_answerable(self):
        self.mutate('qa.jsonl', lambda rows: rows[0].update(reference_claims=[]))
        with self.assertRaisesRegex(ValueError, '参考主张'):
            validate(self.root)

    def test_reject_tampered_source(self):
        path = self.root / 'sources/se-testing.pdf'
        path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            validate(self.root)

    def test_reject_outside_source_path(self):
        self.mutate('documents.jsonl', lambda rows: rows[0].update(file='../outside.pdf'))
        with self.assertRaisesRegex(ValueError, '超出数据目录'):
            validate(self.root)

    def test_export_requires_complete_actual_doc_map(self):
        with self.assertRaisesRegex(ValueError, 'doc-map'):
            export_legacy(self.root, Path(self.tmp.name)/'export', {'se-testing': 1})

    def test_export_preserves_counts_and_mapped_doc_ids(self):
        docs = read_jsonl(self.root/'documents.jsonl')
        mapping = {d['doc']: i+101 for i, d in enumerate(docs)}
        target = Path(self.tmp.name)/'export'
        result = export_legacy(self.root, target, mapping)
        self.assertEqual((result['answerable_exported'], result['refusal_excluded']), (15, 5))
        for doc in docs:
            did = doc['doc']
            qa = json.loads((target/f'{did}.qa.json').read_text('utf-8'))
            self.assertEqual(len(qa), 3)
            self.assertTrue(all(q['doc_ids'] == [mapping[did]] for q in qa))
            with (target/f'{did}.reference.csv').open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))), 4)

    def test_export_rejects_duplicate_mapping(self):
        mapping = {d['doc']: 1 for d in read_jsonl(self.root/'documents.jsonl')}
        with self.assertRaisesRegex(ValueError, '同一 doc_id'):
            export_legacy(self.root, Path(self.tmp.name)/'export', mapping)

    def test_export_cannot_overwrite_dataset(self):
        mapping = {d['doc']: i+1 for i, d in enumerate(read_jsonl(self.root/'documents.jsonl'))}
        with self.assertRaisesRegex(ValueError, '源数据目录'):
            export_legacy(self.root, self.root/'generated', mapping)


if __name__ == '__main__':
    unittest.main()
