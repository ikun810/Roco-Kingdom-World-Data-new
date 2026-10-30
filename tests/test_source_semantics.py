import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))


HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / "tools" / "source_semantics.py"
if not MODULE.exists():
    MODULE = HERE / "source_semantics.py"


class SourceSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "source_semantics.py has not been implemented")
        spec = importlib.util.spec_from_file_location("source_semantics", MODULE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_proto_parser_keeps_aliases_negative_values_and_ignores_comments(self):
        source = """// enum Pretend { WRONG = 99; }
enum Actual {
  option allow_alias = true;
  ZERO = 0;
  ALSO_ZERO = 0; // alias must survive
  NEGATIVE = -2;
}
"""
        parsed = self.mod.parse_proto_enums(source, ["Actual"])
        self.assertEqual(parsed[0]["enum"], "Actual")
        self.assertEqual(parsed[0]["source_line"], 2)
        self.assertEqual(parsed[0]["members"], [
            {"symbol": "ZERO", "value": 0},
            {"symbol": "ALSO_ZERO", "value": 0},
            {"symbol": "NEGATIVE", "value": -2},
        ])
        with self.assertRaisesRegex(ValueError, "Missing enum"):
            self.mod.parse_proto_enums(source, ["Pretend"])

    def test_coverage_distinguishes_omitted_type_from_explicit_zero(self):
        rows = {"7": {"id": 7, "task_condition": [
            {"text": "type omitted"}, {"type": 0}, {"type": 390}, {"type": None}
        ]}}
        original = copy.deepcopy(rows)
        result = self.mod.numeric_coverage(rows, "task_condition", "TaskKeyType", {0: "TKT_NONE"})
        self.assertEqual(result["omitted_type_slots"], 1)
        self.assertEqual(result["invalid_type_slots"], 1)
        self.assertEqual(result["observed_values"], [
            {"value": 0, "symbol_in_historical_enum": "TKT_NONE", "count": 1},
            {"value": 390, "symbol_in_historical_enum": None, "count": 1},
        ])
        self.assertEqual(result["unknown_values"], [390])
        self.assertEqual(result["omitted_source_rows"][0]["pointer"], "/RocoDataRows/7/task_condition/0")
        self.assertEqual(rows, original)

    def test_scene_entries_keep_two_resources_with_same_scene_id(self):
        resources = {
            "10003": {"id": 10003, "scene_id": 103, "scene_export_id": 103,
                      "world_map_entry_npc_content_id": 1},
            "10018": {"id": 10018, "scene_id": 103, "scene_export_id": 1002,
                      "world_map_entry_npc_content_id": 2},
        }
        contents = {
            "1": {"id": 1, "refresh_type": 1, "refresh_param": 11},
            "2": {"id": 2, "refresh_type": 1, "refresh_param": 22},
        }
        areas = {"11": {"id": 11, "scene_res_id": 10003},
                 "22": {"id": 22, "scene_res_id": 10018}}
        result = self.mod.scene_entry_links(resources, contents, areas)
        self.assertEqual([r["scene_res_id"] for r in result], [10003, 10018])
        self.assertEqual([r["scene_id"] for r in result], [103, 103])
        self.assertEqual([r["refresh_param_area_record"]["id"] for r in result], [11, 22])

    def test_checked_source_rejects_mismatched_blob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "source.proto").write_bytes(b"enum Source { ONE = 1; }\n")
            with self.assertRaisesRegex(ValueError, "Git blob"):
                self.mod.checked_source(root, "source.proto", "0" * 40)

    def test_current_archive_guard_requires_registered_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "supplements").mkdir(parents=True)
            (root / "data" / "current.zip").write_bytes(b"different archive")
            (root / "data" / "supplements" / "referenced_content.json").write_text(json.dumps({
                "format": "roco_referenced_content_supplement_v1",
                "target_archive_sha256": "0" * 64,
            }))
            with self.assertRaisesRegex(ValueError, "archive SHA-256"):
                self.mod.validate_target(root)

    def test_generated_anchor_does_not_overwrite_runtime_map_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'build'
            output.mkdir()
            source = output / 'm1_coordinate_anchor_investigation.json'
            source.write_bytes(b'original map bytes')
            with self.assertRaisesRegex(ValueError, 'source'):
                self.mod.write_outputs({'m1_coordinate_anchor_investigation.json': {'new': 1}},
                                       output, root, [source])
            self.assertEqual(source.read_bytes(), b'original map bytes')


if __name__ == "__main__":
    unittest.main()
