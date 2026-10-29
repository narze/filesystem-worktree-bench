import unittest
import hashlib
import json
from pathlib import Path
import tempfile

import bench
from resume import original_batch, pending_samples, recoverable


class ResumeTests(unittest.TestCase):
    def test_only_missing_samples_are_scheduled(self):
        result = {'metadata': {'runs': 10, 'workers': [1, 2, 3, 4]}, 'samples': []}
        full = pending_samples(result)
        self.assertEqual(len(full), 40)
        result['samples'] = [{'round': r, 'workers': w} for r, w in full[:33]]
        self.assertEqual(pending_samples(result), full[33:])
        self.assertEqual(full[33], (9, 3))

    def test_only_worktree_commondir_read_errors_can_be_retried(self):
        self.assertTrue(recoverable(RuntimeError("['worktree', 'add'] failed to read /repo/worktrees/a/commondir: Undefined error: 0")))
        self.assertFalse(recoverable(RuntimeError('offline install failed')))
        self.assertFalse(recoverable(RuntimeError("['worktree', 'add'] No space left on device")))
        self.assertFalse(recoverable(RuntimeError('failed to read /some/commondir')))

    def test_loads_batch_from_the_actual_original_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / 'run'
            root.mkdir()
            (parent / 'host-context.json').write_text(json.dumps({
                'runner_sha256': hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest()}))
            function = original_batch(root, {'metadata': {
                'commit': 'abc', 'pnpm_executable': '/unused/pnpm', 'import_method': 'auto'}})
            self.assertTrue(callable(function))


if __name__ == '__main__':
    unittest.main()
