"""Synthetic tests: no proprietary game data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import content_supplement as mod

class SourceSupplementTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.zip = self.root / "current.zip"
        with ZipFile(self.zip, "w") as z:
            z.writestr("BinDataCompressed/T_CONF.json", json.dumps({"RocoDataRows":{
                "1":{"id":1,"name":"now"},"2":{"id":2,"name":"now"},"3":{"id":3,"name":"now"}}}))
        self.old = self.root / "pakchunk4-WindowsNoEditor/Bin/BinDataCompressed/T_CONF.json"
        self.old.parent.mkdir(parents=True)
        self.rows = {"1":{"id":1,"name":"before"},"2":{"id":2,"name":"before","RewardItem":[2]},
                     "3":{"id":3,"name":"before"},"4":{"id":4,"name":"missing"}}
        raw = json.dumps({"RocoDataRows":self.rows}).encode()
        self.old.write_bytes(raw)
        sha = mod.git_blob_sha(raw)
        def item(id,mode,fields=()):
            return {"table":"T_CONF","id":id,"operation":mode,"fields":list(fields),
                    "source_path":self.old.relative_to(self.root).as_posix(),
                    "source_blob_sha":sha,"record":self.rows[id]}
        self.doc={"format":"roco_referenced_content_supplement_v1","target_archive_sha256":mod.sha256_file(self.zip),
                  "historical_source_commit":"abc123","unresolved":[{"table":"T_CONF","id":"5","reason":"not found"}],
                  "entries":[item("4","add_if_absent"),item("2","backfill_missing_fields",["RewardItem"]),
                             item("3","review_conflict",["name"])]}
    def test_insert_backfill_review(self):
        r=mod.resolve(self.zip,self.doc,self.root)
        self.assertEqual(r["summary"]["resolved_count"],2)
        self.assertEqual(r["summary"]["review_count"],1)
        self.assertEqual(r["summary"]["unresolved_count"],1)
        self.assertEqual(r["resolved_records"][1]["record"]["name"],"now")
        self.assertEqual(r["resolved_records"][1]["record"]["RewardItem"],[2])
        self.assertEqual(r["review_candidates"][0]["current"]["name"],"now")
    def test_target_checksum(self):
        self.doc["target_archive_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"SHA-256"):mod.resolve(self.zip,self.doc,self.root)
    def test_history_checksum(self):
        self.doc["entries"][0]["source_blob_sha"]="a"*40
        with self.assertRaisesRegex(ValueError,"Git blob SHA"):mod.resolve(self.zip,self.doc,self.root)
    def test_no_override_when_already_exists(self):
        e=dict(self.doc["entries"][0])
        e["id"]="1"
        e["record"]=self.rows["1"]
        self.doc["entries"].append(e)
        r=mod.resolve(self.zip,self.doc,self.root)
        self.assertEqual(r["summary"]["existing_id_not_overwritten"],1)
    def test_duplicate_ids(self):
        self.doc["entries"].append(dict(self.doc["entries"][0]))
        with self.assertRaisesRegex(ValueError,"Duplicate"):mod.resolve(self.zip,self.doc,self.root)
    def test_evidence_output_preserves_source_inputs(self):
        before = self.old.read_bytes()
        for destination in (self.zip, self.old, self.root / 'data' / 'new.json'):
            with self.assertRaisesRegex(ValueError, 'source'):
                mod.write_output_json(destination, {'x': 1}, self.root, [self.zip])
        self.assertEqual(self.old.read_bytes(), before)
    def test_evidence_output_creates_destination_parent(self):
        destination = self.root / 'build' / 'evidence.json'
        mod.write_output_json(destination, {'x': 1}, self.root, [self.zip])
        self.assertEqual(json.loads(destination.read_text()), {'x': 1})
if __name__=="__main__":unittest.main()
