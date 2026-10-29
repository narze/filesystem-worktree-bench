import unittest

from report_fs_experiment import summarize
from test_compare import fixture


class FilesystemReportTests(unittest.TestCase):
    def test_pairs_xfs_and_btrfs_by_round(self):
        results={'native-btrfs':fixture(2), 'image-btrfs':fixture(4), 'image-xfs':fixture(3)}
        rows=summarize(results)
        self.assertEqual(rows[0]['paired_xfs_over_btrfs'],.75)
        self.assertEqual(rows[0]['xfs_faster_pairs'],2)
        self.assertEqual(rows[1]['image-xfs']['median'],6)

    def test_rejects_different_workload(self):
        results={'native-btrfs':fixture(2), 'image-btrfs':fixture(4), 'image-xfs':fixture(3)}
        results['image-xfs']['metadata']['commit']='other'
        with self.assertRaises(ValueError):summarize(results)


if __name__=='__main__':unittest.main()
