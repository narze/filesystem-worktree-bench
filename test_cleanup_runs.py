import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cleanup_runs import validate_run


class CleanupTests(unittest.TestCase):
    def fixture(self, root):
        run = root / 'fsbench-test'
        run.mkdir()
        (run / 'trees').mkdir()
        data = {'status': 'complete', 'metadata': {'commit': 'pinned', 'runs': 2, 'workers': [1, 2]},
                'samples': [{'round': n, 'workers': w} for n in (1, 2) for w in (1, 2)]}
        path = run / 'results.json'
        path.write_text(json.dumps(data))
        return run, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_accepts_only_archived_complete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            run, digest = self.fixture(parent)
            self.assertEqual(validate_run(run, parent, digest, 'pinned'), run)
            with self.assertRaises(ValueError):
                validate_run(run, parent, 'different', 'pinned')

    def test_refuses_unfinished_or_nonempty_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            run, digest = self.fixture(parent)
            (run / 'trees' / 'remaining').mkdir()
            with self.assertRaises(ValueError):
                validate_run(run, parent, digest, 'pinned')

    def test_refuses_symlink_or_wrong_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            run, digest = self.fixture(parent)
            alias = parent / 'fsbench-alias'
            alias.symlink_to(run, target_is_directory=True)
            for path, expected in ((alias, parent), (run, parent / 'other')):
                with self.assertRaises(ValueError):
                    validate_run(path, expected, digest, 'pinned')


if __name__ == '__main__':
    unittest.main()
