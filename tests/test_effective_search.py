"""Synthetic cross-table name search and incremental Pak view diff tests."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_catalog
import effective_view
import effective_search


class EffectiveSearchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workdir = Path(temp.name)
        self.before_root = self.workdir / "before"
        self.after_root = self.workdir / "after"
        self.base = "pakchunk4-WindowsNoEditor"
        self.patch = self.base + "_0_P"
        for root in (self.before_root, self.after_root):
            root.mkdir()
        # Entire PETBASE_CONF is replaced. ID 2 disappears from the effective view.
        for root in (self.before_root, self.after_root):
            self.data(root, self.base, "PETBASE_CONF", {
                "1": {"id": 1, "name": "旧喵喵"},
                "2": {"id": 2, "name": "该记录应被覆盖"},
            })
            self.data(root, self.patch, "PETBASE_CONF", {
                "1": {"id": 1, "name": "新喵喵"},
            })
            self.data(root, self.base, "SKILL_CONF", {"101": {"id": 101, "name": "星星魔法"}})
            self.data(root, self.base, "SEASON_CONF", {
                "3": {"id": 3, "s_title": "S3赛季", "s_title_subtitle": "铅字幻梦"},
            })
            self.data(root, self.patch, "WORLD_MAP_CONF", {
                "40": {"id": 40, "zone_name": "月牙湖岸", "desc": "旧地图说明"},
            })
            self.data(root, self.base, "TASK_CONF", {
                "10": {"id": 10, "name": "第一段"},
                "20": {"id": 20, "name": "待移除"},
            })
        self.data(self.before_root, self.base, "NPC_CONF", {"1": {"id": 1, "name": "守卫"}})
        self.data(self.after_root, self.patch, "BAG_ITEM_CONF", {"4": {"id": 4, "name": "魔法石"}})
        self.data(self.after_root, self.patch, "TASK_CONF", {
            "10": {"id": 10, "name": "第一段修订"},
            "30": {"id": 30, "name": "新任务"},
        })
        # Same skill file placed in higher layer, but identical bytes.
        self.data(self.after_root, self.patch, "SKILL_CONF", {"101": {"id": 101, "name": "星星魔法"}})
        self.localize(self.before_root, self.base, "zh_CN", "TASK_CONF", "你好")
        self.localize(self.after_root, self.patch, "zh_CN", "TASK_CONF", "世界")
        self.catalog_before = build_catalog.catalog(self.before_root, "old", "sha-old")
        self.catalog_after = build_catalog.catalog(self.after_root, "new", "sha-new")
        self.before = effective_view.effective_view(self.catalog_before)
        self.after = effective_view.effective_view(self.catalog_after)

    def data(self, root: Path, layer: str, name: str, rows: dict):
        f = root / layer / "Bin" / "BinDataCompressed" / (name + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"RocoDataRows": rows}, ensure_ascii=False), encoding="utf-8")
        return f

    def localize(self, root: Path, layer: str, lang: str, name: str, text: str):
        f = root / layer / "Bin" / "BinLocalize" / lang / (name + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"LocalizationStrings": {"1": text}}, ensure_ascii=False), encoding="utf-8")

    def test_name_search_across_curated_domains(self):
        result = effective_search.name_search(self.before_root, self.before, "魔法")
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["table"], "BinDataCompressed/SKILL_CONF")
        self.assertEqual(result["results"][0]["source_layer"], self.base)

    def test_selected_file_names_only_no_lower_file_row_merge(self):
        result = effective_search.name_search(self.before_root, self.before, "覆盖")
        self.assertEqual(result["total_matches"], 0)
        result = effective_search.name_search(self.before_root, self.before, "喵喵")
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["results"][0]["id"], "1")
        self.assertEqual(result["results"][0]["source_layer"], self.patch)

    def test_maps_and_season_name_fields(self):
        result = effective_search.name_search(self.before_root, self.before, "幻梦", ["season"])
        self.assertEqual(result["total_matches"], 1)
        result = effective_search.name_search(self.after_root, self.after, "月牙湖", ["map"])
        self.assertEqual(result["results"][0]["names"][0]["field"], "zone_name")

    def test_default_ignores_description_fields(self):
        result = effective_search.name_search(self.before_root, self.before, "旧地图说明")
        self.assertEqual(result["total_matches"], 0)

    def test_table_field_override_and_exact(self):
        result = effective_search.name_search(self.before_root, self.before, "旧地图说明",
                                              tables=["WORLD_MAP_CONF"], fields=["desc"])
        self.assertEqual(result["total_matches"], 1)
        result = effective_search.name_search(self.before_root, self.before, "星星",
                                              domains=["skill"], exact=True)
        self.assertEqual(result["total_matches"], 0)

    def test_missing_table_or_domain_fails_closed(self):
        for kw in ({"tables": ["UNREAL_CONF"]}, {"domains": ["unknown"]},
                   {"fields": ["name"]}):
            with self.assertRaises(ValueError):
                effective_search.name_search(self.before_root, self.before, "x", **kw)

    def test_invalid_source_metadata_duplicate_table_rejected(self):
        bad = json.loads(json.dumps(self.before))
        bad["tables"].append(bad["tables"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            effective_search.index_tables(bad)
        bad = json.loads(json.dumps(self.before))
        bad["tables"][0]["data_path"] = "../../secret.json"
        with self.assertRaises(ValueError):
            effective_search.index_tables(bad)

    def test_hash_mismatch_on_search(self):
        self.data(self.before_root, self.patch, "PETBASE_CONF", {"1": {"name": "changed"}})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            effective_search.name_search(self.before_root, self.before, "喵喵", ["pet"])

    def test_metadata_diff_tracks_added_removed_and_changes(self):
        d = effective_search.compare_views(self.before, self.after)
        self.assertEqual(d["tables"]["added"], ["BinDataCompressed/BAG_ITEM_CONF"])
        self.assertEqual(d["tables"]["removed"], ["BinDataCompressed/NPC_CONF"])
        self.assertEqual(d["tables"]["modified"], ["BinDataCompressed/TASK_CONF"])
        self.assertEqual(d["tables"]["relocated_identical_content"],
                         ["BinDataCompressed/SKILL_CONF"])
        self.assertEqual(d["localizations"]["modified"], ["zh_CN/TASK_CONF.json"])
        self.assertTrue(d["priority_inference_only"])
        self.assertNotIn("第一段修订", json.dumps(d, ensure_ascii=False))

    def test_identical_views_have_no_changes(self):
        d = effective_search.compare_views(self.before, self.before)
        self.assertEqual(d["tables"]["modified"], [])
        self.assertEqual(d["tables"]["unchanged"], len(self.before["tables"]))

    def test_optional_row_id_diff_hash_checked_and_no_text(self):
        x = effective_search.row_id_differences(self.before, self.after,
                                                self.before_root, self.after_root)
        task = next(t for t in x["table_diffs"] if t["table"].endswith("TASK_CONF"))
        self.assertEqual(task["added_count"], 1)
        self.assertEqual(task["removed_count"], 1)
        self.assertEqual(task["changed_count"], 1)
        self.assertEqual(task["added_id_sample"], ["30"])
        self.assertNotIn("第一段修订", json.dumps(x, ensure_ascii=False))
        self.assertEqual(len(x["table_diffs"]), 3)

    def test_row_id_diff_detects_tampering(self):
        self.data(self.after_root, self.patch, "TASK_CONF", {"1": {"name": "tampered"}})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            effective_search.row_id_differences(self.before, self.after,
                                                self.before_root, self.after_root)

    def test_query_truncation_and_limits(self):
        result = effective_search.name_search(self.before_root, self.before, "第", limit=1)
        self.assertEqual(len(result["results"]), 1)
        with self.assertRaises(ValueError):
            effective_search.name_search(self.before_root, self.before, "foo", limit=0)
        with self.assertRaises(ValueError):
            effective_search.name_search(self.before_root, self.before, "   ")

    def test_cli_search_and_compare_json_are_portable(self):
        view_old = self.workdir / "old.json"
        view_new = self.workdir / "new.json"
        view_old.write_text(json.dumps(self.before, ensure_ascii=False), encoding="utf-8")
        view_new.write_text(json.dumps(self.after, ensure_ascii=False), encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = effective_search.main(["search", "--root", str(self.before_root),
                                        "--view", str(view_old), "--domain", "pet",
                                        "--query", "新喵喵"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["total_matches"], 1)
        output = self.workdir / "diff.json"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = effective_search.main(["compare", "--before", str(view_old),
                                        "--after", str(view_new), "--output", str(output)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["tables"]["summary"]["modified"], 1)

    def test_cli_no_input_overwrite(self):
        view_file = self.workdir / "old.json"
        view_file.write_text(json.dumps(self.before), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = effective_search.main(["compare", "--before", str(view_file),
                                        "--after", str(view_file), "--output", str(view_file)])
        self.assertEqual(rc, 2)

    def test_legacy_windows_cp1252_stdout_escapes_unicode(self):
        from io import BytesIO, TextIOWrapper
        view_file = self.workdir / "old.json"
        view_file.write_text(json.dumps(self.before), encoding="utf-8")
        buffer = BytesIO()
        writer = TextIOWrapper(buffer, encoding="cp1252", write_through=True)
        with contextlib.redirect_stdout(writer):
            result = effective_search.main(["search", "--root", str(self.before_root),
                                            "--view", str(view_file), "--query", "喵喵"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(buffer.getvalue().decode("cp1252"))["total_matches"], 1)

    def test_comparison_cannot_write_into_pak_source(self):
        out = self.before_root / self.base / "Bin" / "report.json"
        view_file = self.workdir / "old.json"
        view_file.write_text(json.dumps(self.before), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = effective_search.main(["compare", "--before", str(view_file),
                                        "--after", str(view_file), "--output", str(out)])
        self.assertEqual(rc, 2)
        self.assertFalse(out.exists())

    def test_cli_row_id_diff_requires_both_roots(self):
        view_old = self.workdir / "old.json"
        view_old.write_text(json.dumps(self.before), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = effective_search.main(["compare", "--before", str(view_old),
                                        "--after", str(view_old), "--row-ids"])
        self.assertEqual(rc, 2)

    def test_reproducible_diff(self):
        a = effective_search.compare_views(self.before, self.after)
        b = effective_search.compare_views(self.before, self.after)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
