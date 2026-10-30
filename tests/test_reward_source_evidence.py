"""Source drift must invalidate a historical identity report."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import reward_source_evidence as mod


class RewardSourceEvidenceTests(unittest.TestCase):
    def test_changed_identity_bytes_reject_the_registered_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'identity.json'
            path.write_bytes(b'hello\n')
            sha = 'ce013625030ba8dba906f756967f9e9ca394464a'
            self.assertEqual(mod.checked_source_bytes(root, 'identity.json', sha), b'hello\n')
            path.write_bytes(b'hello edited\n')
            with self.assertRaisesRegex(ValueError, 'Git blob'):
                mod.checked_source_bytes(root, 'identity.json', sha)


if __name__ == '__main__':
    unittest.main()
