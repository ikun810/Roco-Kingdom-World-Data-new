"""Synthetic Pak-layer structure tests. No copyrighted files are bundled."""
from argparse import Namespace
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pak_layers as pak
import versioned_db as db


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "public-source"
        self.root.mkdir()
        self.base = "pakchunk4-WindowsNoEditor"
        self.patch = "pakchunk4-WindowsNoEditor_0_P"
        self._row(self.base, "TASK_CONF", {"1": {"id": 1, "name": "base"}})
        self._schema(self.base, "TASK_CONF")
        self._row(self.base, "PET_CONF", {"2": {"id": 2, "name": "pet"}})
        self._schema(self.base, "PET_CONF")
        self._row(self.patch, "TASK_CONF", {"1": {"id": 1, "name": "patch"}})

    def _row(self, layer, table, data):
        p = self.root / layer / "Bin" / "BinDataCompressed" / f"{table}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"RocoDataRows": data}, ensure_ascii=False), encoding="utf-8")

    def _schema(self, layer, table):
        p = self.root / layer / "Bin" / "BinConf" / f"{table}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"UniqueKey": "id", "Properties": [
            {"Name": "id"}, {"Name": "name"}]}), encoding="utf-8")

    def test_layers_are_separate_and_overlays_visible(self):
        x = pak.analyze(self.root)
        self.assertEqual(len(x["layers"]), 2)
        self.assertEqual(x["unique_data_tables"], 2)
        self.assertEqual(x["overlap_tables"], 1)
        self.assertEqual(x["different_hash_overlaps"], 1)
        self.assertEqual(x["tables_without_any_schema"], [])
        self.assertIn("No effective mount order", x["notes"])

    def test_explicit_staging_and_schema_fallback(self):
        result = pak.stage(self.root, [self.base, self.patch], self.root.parent / "build" / "stage")
        self.assertEqual(result["table_count"], 2)
        self.assertEqual(result["cross_layer_schema_count"], 1)
        self.assertFalse(result["order_verified"])
        target = self.root.parent / "build" / "stage"
        data = json.loads((target / "BinDataCompressed" / "TASK_CONF.json").read_text(encoding="utf-8"))
        self.assertEqual(data["RocoDataRows"]["1"]["name"], "patch")
        manifest = json.loads((target / "staging_manifest.json").read_text(encoding="utf-8"))
        task = next(x for x in manifest["selections"] if x["table"] == "TASK_CONF")
        self.assertEqual(task["schema_layer"], self.base)
        self.assertEqual(task["data_layer"], self.patch)
        self.assertEqual(len(task["source_sha256"]), 64)
        self.assertNotIn("data_path", task)

    def test_priority_not_guessed(self):
        with self.assertRaisesRegex(ValueError, "every layer"):
            pak.staged_plan(self.root, [self.patch])
        with self.assertRaisesRegex(ValueError, "every layer"):
            pak.staged_plan(self.root, [self.patch, self.patch])

    def test_priority_can_change_candidate_outcome(self):
        first, _ = pak.staged_plan(self.root, [self.base, self.patch])
        second, _ = pak.staged_plan(self.root, [self.patch, self.base])
        a = next(e for e in first if e["table"] == "TASK_CONF")
        b = next(e for e in second if e["table"] == "TASK_CONF")
        self.assertNotEqual(a["source_sha256"], b["source_sha256"])

    def test_no_overwrite_or_write_inside_source(self):
        target = self.root.parent / "staged"
        pak.stage(self.root, [self.base, self.patch], target)
        with self.assertRaisesRegex(ValueError, "existing"):
            pak.stage(self.root, [self.base, self.patch], target)
        with self.assertRaisesRegex(ValueError, "outside"):
            pak.stage(self.root, [self.base, self.patch], self.root / "build")

    def test_staged_candidate_can_be_ingested(self):
        staged = self.root.parent / "build" / "stage"
        pak.stage(self.root, [self.base, self.patch], staged)
        args = Namespace(data_dir=str(staged / "BinDataCompressed"),
                         schema_dir=str(staged / "BinConf"),
                         database=str(self.root.parent / "build" / "version.sqlite"),
                         snapshot_id="layered-candidate", source_kind="third_party_historical",
                         source_ref="synthetic-layered", source_commit=None,
                         source_date=None, game_build=None, season=None)
        res = db.ingest(args)
        self.assertEqual((res["tables"], res["records"], res["issues"]), (2, 2, 0))

    def test_missing_schema_identified(self):
        self._row(self.patch, "UNKNOWN_CONF", {"1": {"id": 1}})
        plan, report = pak.staged_plan(self.root, [self.base, self.patch])
        self.assertEqual(report["missing_schema_count"], 1)
        self.assertIsNone(next(x for x in plan if x["table"] == "UNKNOWN_CONF")["schema_layer"])

    def test_non_pak_folders_ignored(self):
        (self.root / "other" / "Bin" / "BinDataCompressed").mkdir(parents=True)
        self.assertEqual(len(pak.discover_layers(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
