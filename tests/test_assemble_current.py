"""Synthetic-only archive assembly regression tests."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from assemble_current import assemble


class AssembleCurrentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parts = self.root / 'parts'
        self.parts.mkdir()
        self.input = self.root / 'input.zip'
        with ZipFile(self.input, 'w') as archive:
            archive.writestr('BinConf/X.json', '{}')
            archive.writestr('BinDataCompressed/X.json', '{"RocoDataRows":{"1":{"id":1}}}')
        data = self.input.read_bytes()
        split = len(data)//3
        for i, part in enumerate((data[:split], data[split:split*2], data[split*2:])):
            (self.parts / f'part-{i:03d}.bin').write_bytes(part)
        self.digest = hashlib.sha256(data).hexdigest()
        self.size = len(data)
        self.output = self.root / 'out.zip'

    def test_reassemble_preserves_original(self):
        result = assemble(self.parts, self.output, self.digest, self.size, 2, 3)
        self.assertEqual(result['files'], 2)
        self.assertEqual(self.output.read_bytes(), self.input.read_bytes())

    def test_missing_chunk_rejected(self):
        (self.parts / 'part-001.bin').unlink()
        with self.assertRaisesRegex(ValueError, 'part sequence'):
            assemble(self.parts, self.output, self.digest, self.size, 2, 3)
        self.assertFalse(self.output.exists())

    def test_wrong_digest_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            assemble(self.parts, self.output, '0'*64, self.size, 2, 3)
        self.assertFalse(self.output.exists())

    def test_wrong_expected_files_rejected(self):
        with self.assertRaisesRegex(ValueError, 'file count'):
            assemble(self.parts, self.output, self.digest, self.size, 1, 3)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
