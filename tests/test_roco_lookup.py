from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import roco_lookup  # noqa: E402


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        self.base = "pakchunk4-WindowsNoEditor"
        self.patch = "pakchunk4-WindowsNoEditor_2_P"
        for layer in (self.base, self.patch):
            (self.root / layer / "Bin" / "BinDataCompressed").mkdir(parents=True)
        self.write(self.base, "SEASON_CONF", {
            "1": {"id": 1, "s_title_subtitle": "暗夜拾光"},
            "2": {"id": 2, "s_title_subtitle": "旧赛季"}})
        self.write(self.patch, "SEASON_CONF", {
            "1": {"id": 1, "s_title_subtitle": "暗夜拾光"},
            "2": {"id": 2, "s_title_subtitle": "狂欢怪谈"},
            "3": {"id": 3, "s_title_subtitle": "铅字幻梦"}})

    def write(self, layer, table, rows):
        path = self.root / layer / "Bin" / "BinDataCompressed" / f"{table}.json"
        path.write_text(json.dumps({"RocoDataRows": rows, "LocalizationStrings": {}},
                                   ensure_ascii=False), encoding="utf-8")

    def test_list_layers_and_tables(self):
        self.assertEqual(roco_lookup.layers_in(self.root), [self.base, self.patch])
        r = roco_lookup.table_list(self.root, self.patch, "season")
        self.assertEqual(r["tables"], ["SEASON_CONF"])

    def test_get_record_source_sha_and_no_write(self):
        before = (self.root / self.base / "Bin" / "BinDataCompressed" / "SEASON_CONF.json").read_bytes()
        r = roco_lookup.get_record(self.root, self.base, "SEASON_CONF", "1")
        self.assertEqual(r["row"]["s_title_subtitle"], "暗夜拾光")
        self.assertEqual(len(r["source_sha256"]), 64)
        self.assertEqual(before, (self.root / self.base / "Bin" / "BinDataCompressed" / "SEASON_CONF.json").read_bytes())

    def test_find_results_are_limited(self):
        r = roco_lookup.find_records(self.root, self.patch, "SEASON_CONF", "s_title_subtitle", "幻梦", 1)
        self.assertEqual(r["total_matches"], 1)
        self.assertEqual(r["matches"][0]["id"], "3")
        self.assertFalse(r["truncated"])
        limited = roco_lookup.find_records(self.root, self.patch, "SEASON_CONF", "s_title_subtitle", "拾", 1)
        self.assertEqual(limited["total_matches"], 1)

    def test_find_rejects_bad_args(self):
        for limit in (0, 101):
            with self.assertRaises(ValueError):
                roco_lookup.find_records(self.root, self.patch, "SEASON_CONF", "s_title_subtitle", "赛", limit)
        with self.assertRaises(ValueError):
            roco_lookup.find_records(self.root, self.patch, "SEASON_CONF", "s_title_subtitle", "", 1)

    def test_trace_does_not_infer_priority(self):
        r = roco_lookup.trace_record(self.root, "SEASON_CONF", "2")
        self.assertEqual(len(r["present"]), 2)
        self.assertEqual(r["distinct_row_variants"], 2)
        self.assertFalse(r["pak_priority_verified"])
        r = roco_lookup.trace_record(self.root, "SEASON_CONF", "3")
        self.assertEqual(len(r["present"]), 1)
        self.assertEqual(len(r["absent_or_missing_id"]), 1)

    def test_traversal_and_unknown_layer_refused(self):
        for table in ("../SEASON_CONF", "foo/bar", "foo\\bar", ""):
            with self.assertRaises(ValueError):
                roco_lookup.get_record(self.root, self.base, table, "1")
        with self.assertRaises(ValueError):
            roco_lookup.get_record(self.root, "../../etc", "SEASON_CONF", "1")

    def test_cli_json(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = roco_lookup.main(["--root", str(self.root), "trace", "--table", "SEASON_CONF", "--id", "2"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(buffer.getvalue())["distinct_row_variants"], 2)

    def test_source_symlink_rejected(self):
        target = self.root / self.base / "Bin" / "BinDataCompressed" / "SEASON_CONF.json"
        try:
            link = target.parent / "LINK_CONF.json"
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this OS")
        with self.assertRaises(ValueError):
            roco_lookup.load_table(self.root, self.base, "LINK_CONF")

    def test_invalid_json_rejected(self):
        file = self.root / self.patch / "Bin" / "BinDataCompressed" / "BAD_CONF.json"
        file.write_text('{"RocoDataRows":{"1":{"id":1,"id":2}}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            roco_lookup.load_table(self.root, self.patch, "BAD_CONF")


if __name__ == '__main__':
    unittest.main()
