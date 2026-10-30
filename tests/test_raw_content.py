import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from raw_content import changed_pointers, read_bundle, safe_relative, sha256, without_strings


class RawContentTests(unittest.TestCase):
    def test_absent_null_zero_empty_are_not_collapsed(self):
        for value in (None, 0, [], ""):
            self.assertEqual(changed_pointers({}, {"x": value}), ["/x"])
        self.assertEqual(changed_pointers({"x": None}, {"x": 0}), ["/x"])
        self.assertEqual(changed_pointers({"x": False}, {"x": 0}), ["/x"])

    def test_json_pointer_escaping_and_nested_changed_field(self):
        a = {"a/b~c": [{"text": "old", "count": 3}]}
        b = {"a/b~c": [{"text": "new", "count": 3}]}
        self.assertEqual(changed_pointers(a, b), ["/a~1b~0c/0/text"])
        self.assertEqual(without_strings(a), without_strings(b))
        b["a/b~c"][0]["count"] = 4
        self.assertNotEqual(without_strings(a), without_strings(b))

    def test_source_paths_are_canonical_relative_paths(self):
        for path in ("../x", "/x", "a/../../x", "a\\b", "a//b", "", "./x"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_relative(path)
        self.assertEqual(str(safe_relative("pak/Bin/T.non")), "pak/Bin/T.non")

    def make_bundle(self, root, entries):
        path = root / "source.tar.xz"
        with tarfile.open(path, "w:xz") as archive:
            for name, raw, kind in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(raw) if kind == tarfile.REGTYPE else 0
                if kind == tarfile.SYMTYPE:
                    info.linkname = "target"
                archive.addfile(info, io.BytesIO(raw) if info.isfile() else None)
        data = path.read_bytes()
        return {"bundle": {"path": path.name, "sha256": sha256(data), "byte_length": len(data)},
                "assets": [{"path": "pak/Bin/T.non", "sha256": sha256(b"schema"), "byte_length": 6}]}

    def test_bundle_fingerprints_and_exact_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = self.make_bundle(root, [("pak/Bin/T.non", b"schema", tarfile.REGTYPE)])
            self.assertEqual(read_bundle(root, m), {"pak/Bin/T.non": b"schema"})
            m["assets"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                read_bundle(root, m)
            m["bundle"]["sha256"] = "1" * 64
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                read_bundle(root, m)

    def test_bundle_rejects_missing_extra_duplicate_and_link_members(self):
        cases = [[], [("other", b"schema", tarfile.REGTYPE)],
                 [("pak/Bin/T.non", b"schema", tarfile.REGTYPE)] * 2,
                 [("pak/Bin/T.non", b"", tarfile.SYMTYPE)],
                 [("../T.non", b"schema", tarfile.REGTYPE)]]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for entries in cases:
                with self.subTest(entries=entries):
                    manifest = self.make_bundle(root, entries)
                    with self.assertRaises(ValueError):
                        read_bundle(root, manifest)

    def test_duplicate_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.make_bundle(root, [("pak/Bin/T.non", b"schema", tarfile.REGTYPE)])
            manifest["assets"] *= 2
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                read_bundle(root, manifest)


if __name__ == "__main__":
    unittest.main()
