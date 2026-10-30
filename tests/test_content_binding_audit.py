"""Decoded reward correlations must preserve record identity and field presence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import content_binding_audit as mod


class RewardLimitAliasAuditTests(unittest.TestCase):
    def compare(self, current, historical):
        self.assertTrue(
            callable(getattr(mod, "reward_limit_alias_audit", None)),
            "The reward limit alias audit has not been implemented",
        )
        return mod.reward_limit_alias_audit(current, historical)

    def test_same_presence_counts_with_different_ids_are_not_equal(self):
        result = self.compare(
            {"101": {}, "102": {"RewardItem": []}},
            {"101": {"ObtainLimit": 1}, "102": {}},
        )
        self.assertEqual(result["common_id_count"], 2)
        self.assertEqual(result["historical_limit_present_count"], 1)
        self.assertEqual(result["current_payload_present_count"], 1)
        self.assertFalse(result["presence_sets_equal"])
        self.assertEqual(result["historical_limit_without_current_payload_ids"], ["101"])
        self.assertEqual(result["current_payload_without_historical_limit_ids"], ["102"])

    def test_records_outside_the_common_id_scope_do_not_change_the_audit(self):
        result = self.compare(
            {"1": {"RewardItem": [{"Type": 2, "Count": 5}]},
             "current-only": {"RewardItem": [{"Type": 22, "Count": 9}]}},
            {"1": {"ObtainLimit": 5}, "history-only": {"ObtainLimit": 99}},
        )
        self.assertEqual(result["common_id_count"], 1)
        self.assertEqual(result["historical_limit_present_count"], 1)
        self.assertEqual(result["current_payload_present_count"], 1)
        self.assertTrue(result["presence_sets_equal"])
        self.assertEqual(result["historical_limit_without_current_payload_ids"], [])
        self.assertEqual(result["current_payload_without_historical_limit_ids"], [])
        self.assertEqual(len(result["limit_groups"]), 1)
        self.assertEqual(result["limit_groups"][0]["historical_obtain_limit"], 5)
        self.assertEqual(result["limit_groups"][0]["row_ids"], ["1"])

    def test_one_limit_with_different_payloads_reports_the_counterexample(self):
        result = self.compare(
            {"1": {"RewardItem": [{"Type": 22, "Count": 10}]},
             "2": {"RewardItem": [{"Type": 22, "Count": 20}]},
             "3": {"RewardItem": [{"Count": 10, "Type": 22}]}},
            {"1": {"ObtainLimit": 1}, "2": {"ObtainLimit": 1},
             "3": {"ObtainLimit": 1}},
        )
        group = result["limit_groups"][0]
        self.assertEqual(group["row_ids"], ["1", "2", "3"])
        self.assertEqual(group["current_payload_unique_count"], 2)
        self.assertEqual(result["multiple_payload_limit_group_count"], 1)
        self.assertEqual(
            {variant["payload"][0]["Count"]: variant["count"]
             for variant in group["current_payload_distribution"]},
            {10: 2, 20: 1},
        )
        self.assertEqual(
            {variant["payload"][0]["Count"]: variant["example_row_id"]
             for variant in group["current_payload_distribution"]},
            {10: "1", 20: "2"},
        )

    def test_zero_null_and_empty_values_are_present_and_missing_is_distinct(self):
        result = self.compare(
            {"1": {"RewardItem": 0}, "2": {"RewardItem": None},
             "3": {"RewardItem": []}, "4": {}, "5": {"RewardItem": None}},
            {"1": {"ObtainLimit": 0}, "2": {"ObtainLimit": 0},
             "3": {"ObtainLimit": 0}, "4": {"ObtainLimit": 0},
             "5": {"ObtainLimit": None}},
        )
        self.assertEqual(result["historical_limit_present_count"], 5)
        self.assertEqual(result["current_payload_present_count"], 4)
        self.assertFalse(result["presence_sets_equal"])
        self.assertEqual(result["historical_limit_without_current_payload_ids"], ["4"])
        zero_group = next(g for g in result["limit_groups"]
                          if g["historical_obtain_limit"] == 0)
        self.assertEqual(zero_group["row_ids"], ["1", "2", "3", "4"])
        self.assertEqual(zero_group["current_payload_unique_count"], 4)
        variants = {v["example_row_id"]: v for v in zero_group["current_payload_distribution"]}
        self.assertTrue(variants["1"]["field_present"])
        self.assertEqual(variants["1"]["payload"], 0)
        self.assertTrue(variants["2"]["field_present"])
        self.assertIsNone(variants["2"]["payload"])
        self.assertTrue(variants["3"]["field_present"])
        self.assertEqual(variants["3"]["payload"], [])
        self.assertFalse(variants["4"]["field_present"])
        self.assertNotIn("payload", variants["4"])
        null_group = next(g for g in result["limit_groups"]
                          if g["historical_obtain_limit"] is None)
        self.assertEqual(null_group["row_ids"], ["5"])

    def test_fixed_payloads_per_limit_are_evidence_without_mutating_inputs(self):
        current = {"1": {"RewardItem": [{"Type": 22, "Count": 1000000}]},
                   "2": {"RewardItem": [{"Type": 22, "Count": 1000000}]},
                   "3": {"RewardItem": [{"Type": 1, "Id": 7, "Count": 2}]},
                   "4": {}}
        historical = {"1": {"ObtainLimit": 1}, "2": {"ObtainLimit": 1},
                      "3": {"ObtainLimit": 5}, "4": {}}
        before_current, before_historical = deepcopy(current), deepcopy(historical)
        result = self.compare(current, historical)
        self.assertEqual(result["status"], "not_binary_verified")
        self.assertEqual(result["common_id_count"], 4)
        self.assertTrue(result["presence_sets_equal"])
        self.assertEqual(result["multiple_payload_limit_group_count"], 0)
        self.assertEqual(
            {g["historical_obtain_limit"]: g["row_ids"] for g in result["limit_groups"]},
            {1: ["1", "2"], 5: ["3"]},
        )
        self.assertEqual([g["current_payload_unique_count"] for g in result["limit_groups"]], [1, 1])
        self.assertEqual(current, before_current)
        self.assertEqual(historical, before_historical)

    def test_report_adds_correlation_to_reward_history_without_promoting_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = {"1": {"id": 1, "ObtainLimit": 1,
                                 "RewardItem": [{"Type": 1, "Id": 7, "Count": 1}]}}
            current = {"1": {"id": 1, "RewardItem": [{"Type": 22, "Count": 1000000}]}}
            source_path = "pakchunk4-WindowsNoEditor_0_P/Bin/BinDataCompressed/REWARD_CONF.json"
            source = root / source_path
            source.parent.mkdir(parents=True)
            source_raw = json.dumps({"RocoDataRows": historical}).encode()
            source.write_bytes(source_raw)
            archive_path = root / "data/current.zip"
            archive_path.parent.mkdir()
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("BinDataCompressed/REWARD_CONF.json", json.dumps({"RocoDataRows": current}))
                archive.writestr("BinLocalize/zh_Hans/REWARD_CONF.json", json.dumps({"LocalizationStrings": {}}))
            archive_raw = archive_path.read_bytes()
            supplement_path = root / "data/supplements/referenced_content.json"
            supplement_path.parent.mkdir()
            supplement_path.write_text(json.dumps({
                "target_archive_sha256": hashlib.sha256(archive_raw).hexdigest(),
                "entries": [{
                    "table": "REWARD_CONF", "id": "1", "operation": "review_conflict",
                    "fields": ["RewardItem"], "source_path": source_path,
                    "source_blob_sha": hashlib.sha1(
                        b"blob " + str(len(source_raw)).encode() + b"\0" + source_raw).hexdigest(),
                    "record": historical["1"],
                }],
            }), encoding="utf-8")
            result = mod.audit(root)
            comparison = result["tables"]["REWARD_CONF"]["history_comparisons"][0]
            self.assertIn("reward_limit_alias_audit", comparison)
            self.assertTrue(comparison["reward_limit_alias_audit"]["presence_sets_equal"])
            self.assertEqual(comparison["reward_limit_alias_audit"]["status"], "not_binary_verified")
            self.assertEqual(result["format"], "roco_binding_audit_v1")
            self.assertEqual(comparison["common_id_count"], 1)
            self.assertEqual(comparison["identical_row_count"], 0)
            self.assertEqual(result["candidates"][0]["decision"],
                             "current_runtime_value_requires_binary_or_runtime_evidence")
            self.assertEqual(archive_path.read_bytes(), archive_raw)
            self.assertEqual(source.read_bytes(), source_raw)


if __name__ == "__main__":
    unittest.main()
