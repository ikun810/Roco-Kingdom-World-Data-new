"""Synthetic fixtures only; no game assets or copied dialogue in the test suite."""
from argparse import Namespace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import versioned_db as vdb


class VersionedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "资料源" / "BinDataCompressed"
        self.schema = self.root / "资料源" / "BinConf"
        self.data.mkdir(parents=True)
        self.schema.mkdir(parents=True)
        self.database = self.root / "build" / "versions.sqlite"
        self.set_schema()

    def set_schema(self, name="TASK_CONF.json", props=None):
        props = props or ["id", "name", "next_task"]
        (self.schema / name).write_text(json.dumps({
            "Name": name.removesuffix(".json"), "Type": "EStruct", "UniqueKey": "id",
            "Properties": [{"Name": p, "Type": "EString"} for p in props]}), encoding="utf-8")

    def rows(self, rows, name="TASK_CONF.json"):
        (self.data / name).write_text(json.dumps({"RocoDataRows": rows, "LocalizationStrings": {}},
                                                      ensure_ascii=False), encoding="utf-8")

    def args(self, snapshot_id="v1", **kwargs):
        defaults = dict(data_dir=str(self.data), schema_dir=str(self.schema), database=str(self.database),
                        snapshot_id=snapshot_id, source_kind="third_party_historical",
                        source_ref="https://example.org/source", source_commit="a" * 40,
                        source_date="2026-04-13", game_build=None, season=None)
        defaults.update(kwargs)
        return Namespace(**defaults)

    def test_two_versions_and_entity_diff(self):
        self.rows({"1": {"id": 1, "name": "旧"}, "2": {"id": 2, "name": "保留"}})
        v1 = vdb.ingest(self.args("v1"))
        self.assertEqual((v1["tables"], v1["records"], v1["status"]), (1, 2, "created"))
        self.assertEqual(vdb.ingest(self.args("v1"))["status"], "unchanged")
        self.rows({"1": {"id": 1, "name": "新"}, "3": {"id": 3, "name": "新增"}})
        vdb.ingest(self.args("v2"))
        result = vdb.compare(Namespace(before="v1", after="v2", database=str(self.database)))
        diff = result["tables_changed"][0]
        self.assertEqual((diff["added"], diff["removed"], diff["modified"]), (1, 1, 1))
        self.assertEqual(diff["sample_modified"], ["1"])
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 4)

    def test_snapshot_id_conflict_not_overwritten(self):
        self.rows({"1": {"id": 1}})
        vdb.ingest(self.args())
        self.rows({"1": {"id": 1, "value": "different"}})
        with self.assertRaisesRegex(ValueError, "already used"):
            vdb.ingest(self.args())
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_metadata_conflict_not_overwritten(self):
        self.rows({"1": {"id": 1}})
        vdb.ingest(self.args())
        with self.assertRaisesRegex(ValueError, "already used"):
            vdb.ingest(self.args(game_build="unverified"))

    def test_invalid_source_rolls_back_every_table(self):
        self.rows({"1": {"id": 1}})
        (self.data / "ZZ.json").write_text('{"RocoDataRows": []}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RocoDataRows"):
            vdb.ingest(self.args())
        with sqlite3.connect(self.database) as db:
            for table in ["snapshots", "records", "source_files"]:
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_missing_id_and_inconsistent_id_are_issues(self):
        self.rows({"1": {"id": 9}, "2": {"name": "missing"}})
        result = vdb.ingest(self.args())
        self.assertEqual(result["issues"], 2)
        manifest = vdb.report_manifest(Namespace(database=str(self.database), snapshot_id="v1"))
        self.assertEqual(manifest["quality_issue_counts"],
                         {"missing_unique_key": 1, "unique_key_mismatch": 1})

    def test_missing_schema_reports_issue_and_preserves_records(self):
        self.rows({"1": {"id": 1}})
        (self.schema / "TASK_CONF.json").unlink()
        result = vdb.ingest(self.args())
        self.assertEqual((result["records"], result["issues"]), (1, 1))
        m = vdb.report_manifest(Namespace(database=str(self.database), snapshot_id="v1"))
        self.assertEqual(m["quality_issue_counts"], {"missing_schema": 1})

    def test_schema_not_supplied_explicitly_reported(self):
        self.rows({"1": {"id": 1}})
        result = vdb.ingest(self.args(schema_dir=None))
        self.assertEqual(result["issues"], 1)

    def test_zero_row_table_is_valid(self):
        self.rows({})
        result = vdb.ingest(self.args())
        self.assertEqual((result["tables"], result["records"]), (1, 0))

    def test_schema_field_change_in_diff_without_row_change(self):
        self.rows({"1": {"id": 1, "name": "unchanged"}})
        vdb.ingest(self.args("old"))
        self.set_schema(props=["id", "name", "next_task", "new_field"])
        vdb.ingest(self.args("new"))
        diff = vdb.compare(Namespace(database=str(self.database), before="old", after="new"))
        row = diff["tables_changed"][0]
        self.assertEqual((row["modified"], row["schema_changed"]), (0, True))
        self.assertEqual(row["schema_fields_added"], ["new_field"])

    def test_raw_file_format_change_is_not_semantic_change(self):
        self.rows({"1": {"id": 1, "name": "abc"}})
        vdb.ingest(self.args("old"))
        (self.data / "TASK_CONF.json").write_text(
            '{  "LocalizationStrings":{}, "RocoDataRows" :{"1":{"name":"abc", "id":1}} }',
            encoding="utf-8")
        vdb.ingest(self.args("new"))
        changes = vdb.compare(Namespace(database=str(self.database), before="old", after="new"))["tables_changed"]
        self.assertEqual((changes[0]["source_bytes_changed"], changes[0]["modified"]), (True, 0))

    def test_manifest_only_metadata_not_source_text(self):
        self.rows({"1": {"id": 1, "name": "PRIVATE_TEST_TEXT"}})
        vdb.ingest(self.args())
        manifest = vdb.report_manifest(Namespace(database=str(self.database), snapshot_id="v1"))
        self.assertNotIn("PRIVATE_TEST_TEXT", json.dumps(manifest))
        self.assertEqual(manifest["tables"][0]["declared_fields"], ["id", "name", "next_task"])

    def test_inventory_reports_hashes_and_field_sets_without_row_content(self):
        self.rows({"1": {"id": 1, "name": "PRIVATE_TEST_TEXT"}})
        inventory = vdb.inventory_report(Namespace(data_dir=str(self.data), schema_dir=str(self.schema)))
        self.assertEqual((inventory["total_tables"], inventory["total_records"]), (1, 1))
        self.assertEqual(len(inventory["tables"][0]["source_sha256"]), 64)
        self.assertNotIn("PRIVATE_TEST_TEXT", json.dumps(inventory, ensure_ascii=False))

    def test_verify_hashes_and_modified_files(self):
        self.rows({"1": {"id": 1}})
        vdb.ingest(self.args())
        args = Namespace(database=str(self.database), snapshot_id="v1", data_dir=str(self.data),
                         schema_dir=str(self.schema))
        self.assertTrue(vdb.verify(args)["verified"])
        self.rows({"1": {"id": 1, "name": "different"}})
        result = vdb.verify(args)
        self.assertFalse(result["verified"])
        self.assertEqual(result["mismatches"][0]["issue"], "source_hash_mismatch")

    def test_verify_database_record_hash_and_count(self):
        self.rows({"1": {"id": 1}, "2": {"id": 2}})
        vdb.ingest(self.args())
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE records SET payload_json=? WHERE snapshot_id=? AND record_id=?",
                       ('{"id": 99}', "v1", "1"))
            db.execute("DELETE FROM records WHERE snapshot_id=? AND record_id=?", ("v1", "2"))
        args = Namespace(database=str(self.database), snapshot_id="v1", data_dir=str(self.data),
                         schema_dir=str(self.schema))
        result = vdb.verify(args)
        self.assertFalse(result["verified"])
        self.assertEqual(result["checked_database_records"], 1)
        self.assertIn("database_record_hash_mismatch", [x["issue"] for x in result["mismatches"]])
        self.assertIn("database_record_count_mismatch", [x["issue"] for x in result["mismatches"]])

    def test_database_record_integrity_clean(self):
        self.rows({"1": {"id": 1}})
        vdb.ingest(self.args())
        result = vdb.verify(Namespace(database=str(self.database), snapshot_id="v1",
                                     data_dir=str(self.data), schema_dir=str(self.schema)))
        self.assertTrue(result["verified"])
        self.assertEqual(result["sqlite_integrity_check"], "ok")
        self.assertEqual(result["checked_database_records"], 1)

    def test_verify_schema_hash(self):
        self.rows({"1": {"id": 1}})
        vdb.ingest(self.args())
        self.set_schema(props=["id", "changed"])
        args = Namespace(database=str(self.database), snapshot_id="v1", data_dir=str(self.data),
                         schema_dir=str(self.schema))
        self.assertEqual(vdb.verify(args)["mismatches"][0]["issue"], "schema_hash_mismatch")

    def test_verify_added_file(self):
        self.rows({"1": {"id": 1}})
        vdb.ingest(self.args())
        self.rows({}, name="EXTRA.json")
        args = Namespace(database=str(self.database), snapshot_id="v1", data_dir=str(self.data),
                         schema_dir=str(self.schema))
        self.assertEqual(vdb.verify(args)["mismatches"][0]["issue"], "unexpected_source_file")

    def test_invalid_utf8_fails(self):
        (self.data / "TASK_CONF.json").write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "Invalid UTF-8"):
            vdb.ingest(self.args())

    def test_duplicate_json_keys_are_rejected(self):
        (self.data / "TASK_CONF.json").write_text('{"RocoDataRows":{"1":{"id":1,"id":2}}}',
                                                  encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            vdb.ingest(self.args())

    def test_invalid_schema_is_rejected(self):
        self.rows({"1": {"id": 1}})
        (self.schema / "TASK_CONF.json").write_text('{"Properties":{}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Properties"):
            vdb.ingest(self.args())

    def test_changed_file_mid_scan_rejected(self):
        self.rows({"1": {"id": 1}})
        target = self.data / "TASK_CONF.json"
        old_hash = vdb.hash_file(target)
        target.write_text('{"RocoDataRows": {}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            vdb.parse_json_file(target, old_hash)

    def test_database_inside_source_directory_refused(self):
        self.rows({"1": {"id": 1}})
        with self.assertRaisesRegex(ValueError, "Refusing"):
            vdb.ingest(self.args(database=str(self.data / "out.sqlite")))

    def test_nonexistent_database_read_does_not_create(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            vdb.report_manifest(Namespace(database=str(self.database), snapshot_id="v1"))
        self.assertFalse(self.database.exists())

    def test_legacy_database_requires_new_path(self):
        self.rows({"1": {"id": 1}})
        self.database.parent.mkdir(parents=True)
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE snapshots(snapshot_id TEXT)")
        with self.assertRaisesRegex(ValueError, "Legacy unversioned"):
            vdb.ingest(self.args())

    def test_cli_inventory_writes_report(self):
        self.rows({"1": {"id": 1}})
        report = self.root / "build" / "inventory.json"
        result = vdb.main(["inventory", "--data-dir", str(self.data), "--schema-dir", str(self.schema),
                           "--output", str(report)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["total_tables"], 1)


if __name__ == "__main__":
    unittest.main()
