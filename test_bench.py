import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('bench.py')


class BenchmarkTests(unittest.TestCase):
    def test_seed_store_preserves_dangling_project_links(self):
        from bench import copy_seed_store
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / 'seed'
            projects = seed / 'v11/projects'
            projects.mkdir(parents=True)
            (projects / 'deleted-worktree').symlink_to(root / 'removed/node_modules')
            (seed / 'package-content').write_text('cached package')
            target = root / 'copy'
            copy_seed_store(seed, target)
            self.assertTrue((target / 'v11/projects/deleted-worktree').is_symlink())
            self.assertEqual((target / 'package-content').read_text(), 'cached package')

    def test_real_worktrees_are_removed_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args], text=True)
            git('init', '-q')
            (source / 'sample.txt').write_text('representative content\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')
            before = git('worktree', 'list', '--porcelain')
            target = root / 'target'
            target.mkdir()
            subprocess.run([sys.executable, str(SCRIPT), '--source', str(source),
                            '--target', str(target), '--workers', '1', '2', '3', '4',
                            '--runs', '2', '--warmups', '1', '--skip-install'], check=True,
                           stdout=subprocess.DEVNULL)
            result_dir, = target.glob('fsbench-*')
            result = json.loads((result_dir / 'results.json').read_text())
            self.assertEqual(len(result['samples']), 8)
            self.assertEqual({s['workers'] for s in result['samples']}, {1, 2, 3, 4})
            for sample in result['samples']:
                self.assertEqual(len(sample['checkout']['worker_seconds']), sample['workers'])
                self.assertGreater(sample['total_seconds'], 0)
                self.assertNotIn('install', sample)
            self.assertEqual(git('status', '--porcelain'), '')
            self.assertEqual(git('worktree', 'list', '--porcelain'), before)
            self.assertFalse(any((result_dir / 'trees').iterdir()))
            self.assertTrue((result_dir / 'results.csv').exists())

    def test_invalid_worker_count_fails_without_creating_data(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--source', '.',
                                 '--workers', '0'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_offline_install_failure_is_saved_and_scratch_trees_are_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (source / 'package.json').write_text('{"packageManager":"pnpm@1.2.3"}')
            (source / 'pnpm-lock.yaml').write_text('fixture lockfile\n')
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args], text=True)
            git('init', '-q')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')
            pnpm = root / 'fake-pnpm'
            pnpm.write_text(f'#!{sys.executable}\n' + '''import sys
from pathlib import Path
if '--version' in sys.argv:
    print('1.2.3')
elif '--offline' in sys.argv:
    print('intentional offline failure')
    sys.exit(9)
else:
    assert '--ignore-scripts' in sys.argv
    assert '--frozen-lockfile' in sys.argv
    Path('node_modules').mkdir()
''')
            pnpm.chmod(0o755)
            target = root / 'target'
            result = subprocess.run([sys.executable, str(SCRIPT), '--source', str(source),
                                     '--target', str(target), '--pnpm', str(pnpm),
                                     '--workers', '2', '--runs', '1'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            result_dir, = target.glob('fsbench-*')
            data = json.loads((result_dir / 'results.json').read_text())
            self.assertEqual(data['status'], 'failed')
            self.assertIn('intentional offline failure', data['error'])
            self.assertEqual(data['samples'], [])
            self.assertFalse(any((result_dir / 'trees').iterdir()))
            self.assertFalse((result_dir / 'prepare').exists())
            self.assertEqual(git('status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
