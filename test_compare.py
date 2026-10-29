import copy
import unittest

from compare import comparison, render


def fixture(seconds):
    return {'status': 'complete', 'metadata': {
        'commit': 'abc', 'node_version': 'v24.22.1', 'pnpm_version': '11.18.0',
        'import_method': 'auto', 'install_scripts': False, 'runs': 2,
        'cache': 'warm', 'durability': 'command completion', 'lifecycle': 'stage barriers',
        'workers': [1, 2], 'lockfile_sha256_normalized': 'same'},
        'samples': [{'workers': w, 'round': number, 'total_seconds': seconds * w,
                     **{stage: {'batch_seconds': seconds * w / 3}
                        for stage in ('checkout', 'install', 'delete')}}
                    for w in (1, 2) for number in range(1, 3)]}


class CompareTests(unittest.TestCase):
    def test_compares_equal_work_at_each_worker_count(self):
        rows = comparison(fixture(2), fixture(4))
        self.assertEqual(rows[0]['mac_over_linux'], 2)
        self.assertEqual(rows[1]['mac']['throughput'], 0.25)
        self.assertEqual(rows[1]['linux']['total'], 4)

    def test_rejects_mismatched_workload(self):
        for field in ('commit', 'pnpm_version', 'node_version', 'import_method',
                      'lockfile_sha256_normalized', 'workers', 'runs'):
            with self.subTest(field=field):
                changed = copy.deepcopy(fixture(4))
                changed['metadata'][field] = 'different'
                with self.assertRaises(ValueError):
                    comparison(fixture(2), changed)

    def test_rejects_incomplete_sample_count(self):
        changed = fixture(4)
        changed['samples'].pop()
        with self.assertRaises(ValueError):
            comparison(fixture(2), changed)

    def test_report_discloses_failed_attempts_and_resume(self):
        linux, mac = fixture(2), fixture(4)
        mac['discarded_attempts'] = [{'error': 'Git checkout failed'}]
        html = render(linux, comparison(linux, mac), mac)
        self.assertIn('1 failed', html)
        self.assertIn('resumed', html)

    def test_rejects_duplicate_rounds_even_with_correct_sample_count(self):
        changed = fixture(4)
        changed['samples'][1] = copy.deepcopy(changed['samples'][0])
        with self.assertRaises(ValueError):
            comparison(fixture(2), changed)


if __name__ == '__main__':
    unittest.main()
