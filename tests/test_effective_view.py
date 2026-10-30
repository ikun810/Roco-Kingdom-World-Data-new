"""Tests for candidate file-level Pak priority overlays (no game data)."""
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


class EffectiveViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.base = "pakchunk4-WindowsNoEditor"
        self.patch0 = self.base + "_0_P"
        self.patch1 = self.base + "_1_P"
        self.patch3 = self.base + "_3_P"
        self.fixture()
        self.catalog = build_catalog.catalog(self.root, source_commit="commit0123")

    def data(self, layer, kind, table, rows):
        f = self.root / layer / "Bin" / kind / (table + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"RocoDataRows": rows}, ensure_ascii=False), encoding="utf-8")
        return f

    def fixture(self):
        self.data(self.base, "BinDataCompressed", "TASK_CONF", {
            "1": {"id": 1, "name": "old"}, "2": {"id": 2, "name": "removed"}})
        self.data(self.patch0, "BinDataCompressed", "TASK_CONF", {"1": {"id": 1, "name": "new"}})
        self.data(self.patch3, "BinDataCompressed", "TASK_CONF", {})
        self.data(self.base, "BinDataCompressed", "PET_CONF", {"9": {"id": 9, "name": "pet"}})
        self.data(self.patch1, "BinData", "NPC_CONF", {"3": {"id": 3, "name": "npc"}})
        schema = self.root / self.base / "Bin" / "BinConf" / "PET_CONF.json"
        schema.parent.mkdir(parents=True)
        schema.write_text(json.dumps({"UniqueKey": "id", "Properties": [{"Name": "id"}]}))
        loc_base = self.root / self.base / "Bin" / "BinLocalize" / "zh_CN" / "PET_CONF.json"
        loc_base.parent.mkdir(parents=True)
        loc_base.write_text(json.dumps({"LocalizationStrings": {"1": "hello"}}))
        loc_patch = self.root / self.patch0 / "Bin" / "BinLocalize" / "zh_CN" / "PET_CONF.json"
        loc_patch.parent.mkdir(parents=True)
        loc_patch.write_text(json.dumps({"LocalizationStrings": {"1": "你好"}}, ensure_ascii=False), encoding="utf-8")

    def test_standard_priority_order(self):
        self.assertEqual(effective_view.standard_order([
            self.patch3, self.patch1, self.base, self.patch0]),
            [self.base, self.patch0, self.patch1, self.patch3])

    def test_latest_file_completely_replaces_lower_rows(self):
        view = effective_view.effective_view(self.catalog)
        task = effective_view.select_table(view, "TASK_CONF")
        self.assertEqual(task["data_layer"], self.patch3)
        self.assertEqual(task["row_count"], 0)
        self.assertEqual(effective_view.load_selected_rows(self.root, task), {})
        self.assertEqual(task["superseded_layers"], [self.base, self.patch0])
        self.assertEqual(view["summary"]["effective_rows"], 2)
        self.assertEqual(view["summary"]["not_selected_source_rows"], 3)
        self.assertFalse(view["pak_mount_order_verified"])

    def test_patch_missing_file_inherits_previous(self):
        view = effective_view.effective_view(self.catalog)
        pet = effective_view.select_table(view, "PET_CONF")
        self.assertEqual(pet["data_layer"], self.base)
        self.assertEqual(pet["schema_source_layer"], self.base)
        npc = effective_view.select_table(view, "BinData/NPC_CONF")
        self.assertEqual(npc["data_layer"], self.patch1)
        self.assertEqual(view["summary"]["effective_table_kinds"], 3)

    def test_explicit_nonstandard_order_supported_but_not_verified(self):
        view = effective_view.effective_view(self.catalog, [self.patch3, self.patch0, self.patch1, self.base])
        self.assertEqual(effective_view.select_table(view, "TASK_CONF")["row_count"], 2)
        self.assertFalse(view["pak_mount_order_verified"])
        self.assertEqual(view["priority_selection_method"], "operator_supplied_unverified")

    def test_localization_overlay_preserves_language(self):
        view = effective_view.effective_view(self.catalog)
        self.assertEqual(len(view["localizations"]), 1)
        self.assertEqual(view["localizations"][0]["data_layer"], self.patch0)

    def test_invalid_priority_rejected(self):
        with self.assertRaises(ValueError):
            effective_view.effective_view(self.catalog, [self.base, self.patch0])
        with self.assertRaises(ValueError):
            effective_view.standard_order([self.base, self.base])
        with self.assertRaises(ValueError):
            effective_view.standard_order(["pakchunk4-WindowsNoEditor", "pakchunk5-WindowsNoEditor"])

    def test_metadata_is_reproducible_and_content_free(self):
        a = effective_view.effective_view(self.catalog)
        b = effective_view.effective_view(self.catalog)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertNotIn("removed", json.dumps(a))
        self.assertNotIn("你好", json.dumps(a, ensure_ascii=False))

    def test_reject_conflicting_duplicate_layers_and_bad_file_paths(self):
        a = json.loads(json.dumps(self.catalog))
        a["tables"][0]["copies"].append(dict(a["tables"][0]["copies"][0]))
        with self.assertRaises(ValueError):
            effective_view.effective_view(a)
        b = json.loads(json.dumps(self.catalog))
        b["tables"][0]["copies"][0]["path"] = "../../bad.json"
        with self.assertRaises(ValueError):
            effective_view.effective_view(b)

    def test_source_changed_since_catalog_detected_on_lookup(self):
        view = effective_view.effective_view(self.catalog)
        entry = effective_view.select_table(view, "PET_CONF")
        self.data(self.base, "BinDataCompressed", "PET_CONF", {"9": {"name": "modified"}})
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            effective_view.load_selected_rows(self.root, entry)

    def test_cli_build_and_effective_lookup(self):
        catalog = self.root / "build" / "catalog.json"
        view_path = self.root / "build" / "view.json"
        summary = self.root / "build" / "summary.json"
        catalog.parent.mkdir(parents=True)
        catalog.write_text(json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(effective_view.main(["build", "--catalog", str(catalog),
                                                  "--output", str(view_path), "--summary", str(summary)]), 0)
        self.assertEqual(json.loads(summary.read_text())["summary"]["effective_rows"], 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = effective_view.main(["get", "--view", str(view_path), "--root", str(self.root),
                                      "--table", "PET_CONF", "--id", "9"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue())["record"]["name"], "pet")

    def test_cli_find_and_removed_id(self):
        view_file = self.root / "effective.json"
        view_file.write_text(json.dumps(effective_view.effective_view(self.catalog)), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = effective_view.main(["find", "--view", str(view_file), "--root", str(self.root),
                                      "--table", "PET_CONF", "--field", "name", "--contains", "pet"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue())["total_matches"], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(effective_view.main(["get", "--view", str(view_file), "--root", str(self.root),
                                                  "--table", "TASK_CONF", "--id", "2"]), 2)

    def test_no_untrusted_output_same_as_input(self):
        path = self.root / "catalog.json"
        path.write_text(json.dumps(self.catalog))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(effective_view.main(["build", "--catalog", str(path),
                                                  "--output", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
