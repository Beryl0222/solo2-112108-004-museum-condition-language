"""核对合成资料的字段和业务记录引用。"""
import json
from pathlib import Path
import unittest

from read_materials import read_collection

ROOT = Path(__file__).resolve().parents[1] / "data"


class MaterialsTests(unittest.TestCase):
    def test_collections_follow_manifest(self):
        manifest = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual({path.stem for path in ROOT.glob("*.jsonl")}, set(manifest))
        for name in manifest:
            with self.subTest(name=name):
                self.assertTrue(read_collection(ROOT, name))

    def test_source_identities_are_distinct(self):
        rows = read_collection(ROOT, 'views')
        identities = {tuple(row[key] for key in ('id',)) for row in rows}
        self.assertEqual(len(identities), len(rows))

    def test_relation_points_to_existing_record(self):
        targets = {row['id'] for row in read_collection(ROOT, 'views')}
        for row in read_collection(ROOT, 'reports'):
            for identifier in row['references']:
                self.assertIn(identifier, targets)
