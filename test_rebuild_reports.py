import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from rebuild_reports import bundle


class BundleTests(unittest.TestCase):
    def test_manifest_matches_archived_bytes_and_omits_appledouble(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'results.json').write_text('{"samples": []}\n')
            (root / '._results.json').write_text('resource fork')
            bundle(root, 'test', [root / 'results.json', root / '._results.json'], {'scored_batches': 0})
            manifest = json.loads((root / 'test-manifest.json').read_text())
            with zipfile.ZipFile(root / 'test.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'results.json', 'test-manifest.json'})
                for name, digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
