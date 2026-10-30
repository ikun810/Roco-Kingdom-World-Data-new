"""Synthetic-only tests for content-free full-layer catalog generation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_catalog as cat


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.base = "pakchunk4-WindowsNoEditor"
        self.patch = "pakchunk4-WindowsNoEditor_0_P"

    def _write(self, layer, subdir, name, data):
        path = self.root / layer / "Bin" / subdir / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def fixture(self):
        self._write(self.base, "BinConf", "TASK_CONF", {
            "UniqueKey": "id", "Properties": [{"Name": "id"}, {"Name": "name"}]})
        self._write(self.base, "BinDataCompressed", "TASK_CONF", {
            "RocoDataRows": {"1": {"id": 1, "name": "序章"}, "2": {"id": 2, "name": "主线"}},
            "LocalizationStrings": {"1": "你好"}})
        self._write(self.patch, "BinDataCompressed", "TASK_CONF", {
            "RocoDataRows": {"1": {"id": 1, "name": "新序章"}}})
        self._write(self.base, "BinData", "NPC_CONF", {"RocoDataRows": {}})
        self._write(self.patch, "BinLocalize/zh_Hans", "TASK_CONF", {"LocalizationStrings": {"1": "新"}})

    def test_full_layer_counts_and_no_effective_layer(self):
        self.fixture()
        result = cat.catalog(self.root, source_commit="abc123")
        summary = result["summary"]
        self.assertEqual(summary["layer_count"], 2)
        self.assertEqual(summary["data_files"], 3)
        self.assertEqual(summary["compressed_files"], 2)
        self.assertEqual(summary["uncompressed_files"], 1)
        self.assertEqual(summary["schema_files"], 1)
        self.assertEqual(summary["localization_files"], 1)
        self.assertEqual(summary["unique_compressed_table_names"], 1)
        self.assertEqual(summary["overlapping_table_kinds"], 1)
        self.assertEqual(summary["total_rows_across_layers"], 3)
        self.assertFalse(result["pak_mount_order_verified"])
        self.assertEqual(result["source_commit"], "abc123")
        table = next(x for x in result["tables"] if x["table"] == "BinDataCompressed/TASK_CONF")
        self.assertTrue(table["overlap"])
        self.assertTrue(table["different_content_hashes"])
        self.assertTrue(table["copies"][0]["schema_in_same_layer"])
        self.assertFalse(table["copies"][1]["schema_in_same_layer"])
        self.assertEqual(table["copies"][0]["observed_fields"], ["id", "name"])
        self.assertEqual(table["copies"][0]["localization_string_count"], 1)
        self.assertNotIn("序章", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("新序章", json.dumps(result, ensure_ascii=False))

    def test_output_reproducible_and_source_unchanged(self):
        self.fixture()
        source = self.root / self.base / "Bin" / "BinDataCompressed" / "TASK_CONF.json"
        before = source.read_bytes()
        out = self.root / "build" / "catalog.json"
        small = self.root / "build" / "summary.json"
        args = ["--root", str(self.root), "--output", str(out), "--summary", str(small), "--strict"]
        self.assertEqual(cat.main(args), 0)
        first = out.read_bytes()
        self.assertEqual(cat.main(args), 0)
        self.assertEqual(first, out.read_bytes())
        self.assertEqual(before, source.read_bytes())
        self.assertIn("summary", json.loads(small.read_text(encoding="utf-8")))
        self.assertNotIn("tables", json.loads(small.read_text(encoding="utf-8")))

    def test_malformed_table_logged_and_strict_fails(self):
        self.fixture()
        p = self._write(self.base, "BinDataCompressed", "BROKEN", {"RocoDataRows": {}})
        p.write_text("{invalid json", encoding="utf-8")
        out = self.root / "build" / "catalog.json"
        small = self.root / "build" / "summary.json"
        self.assertEqual(cat.main(["--root", str(self.root), "--output", str(out),
                                   "--summary", str(small), "--strict"]), 1)
        issues = json.loads(small.read_text(encoding="utf-8"))["issues"]
        self.assertTrue(any(z["code"] == "parse_error" for z in issues))

    def test_invalid_envelope_and_row_shapes_reported(self):
        self.fixture()
        self._write(self.patch, "BinDataCompressed", "MALFORMED", {"RocoDataRows": [1, 2]})
        self._write(self.patch, "BinDataCompressed", "ODD", {"RocoDataRows": {"1": 5}})
        result = cat.catalog(self.root)
        self.assertIn("invalid_data_rows", [x["code"] for x in result["issues"]])
        self.assertIn("invalid_row_shape", [x["code"] for x in result["issues"]])

    def test_empty_schema_candidates_not_assumed(self):
        self.fixture()
        table = next(x for x in cat.catalog(self.root)["tables"]
                     if x["table"] == "BinData/NPC_CONF")
        self.assertEqual(table["candidate_schemas"], [])

    def test_write_inside_pak_refused(self):
        self.fixture()
        out = self.root / self.base / "bad.json"
        rc = cat.main(["--root", str(self.root), "--output", str(out)])
        self.assertEqual(rc, 2)
        self.assertFalse(out.exists())

    def test_outputs_must_differ(self):
        self.fixture()
        x = self.root / "build" / "index.json"
        self.assertEqual(cat.main(["--root", str(self.root), "--output", str(x),
                                   "--summary", str(x)]), 2)

    def test_missing_root_errors(self):
        with self.assertRaises(ValueError):
            cat.catalog(self.root / "missing")

    def test_no_pak_errors(self):
        with self.assertRaises(ValueError):
            cat.catalog(self.root)

    def test_non_data_folder_ignored(self):
        self.fixture()
        (self.root / "some-other-dir").mkdir()
        self.assertEqual(cat.catalog(self.root)["summary"]["layer_count"], 2)


if __name__ == "__main__":
    unittest.main()
