import copy
import unittest

from compare_all import combined, filesystem
from test_compare import fixture


class CompareAllTests(unittest.TestCase):
    def test_macos_platform_name_uses_apfs_label(self):
        result = {'metadata': {'mount': 'Filesystem /dev/disk3s5',
                               'platform': 'macOS-26.6.2-arm64-arm-64bit-Mach-O'}}
        self.assertEqual(filesystem(result), 'apfs')

    def test_same_work_is_compared_across_three_machines(self):
        rows = combined(fixture(2), fixture(4), fixture(6))
        self.assertEqual(rows[1]['desktop']['total'], 4)
        self.assertEqual(rows[1]['mac']['total'], 8)
        self.assertEqual(rows[1]['thinkpad']['total'], 12)
        self.assertAlmostEqual(rows[1]['thinkpad']['throughput'], 1 / 6)

    def test_rejects_mismatched_thinkpad_settings(self):
        other = copy.deepcopy(fixture(6))
        other['metadata']['commit'] = 'wrong'
        with self.assertRaises(ValueError):
            combined(fixture(2), fixture(4), other)

    def test_optional_fourth_machine_uses_same_workload_validation(self):
        rows = combined(fixture(2), fixture(4), fixture(6), fixture(8))
        self.assertEqual(rows[1]['debianarze']['total'], 16)
        changed = fixture(8)
        changed['metadata']['node_version'] = 'wrong'
        with self.assertRaises(ValueError):
            combined(fixture(2), fixture(4), fixture(6), changed)

    def test_optional_m1_pro_is_compared_with_the_same_workload(self):
        rows = combined(fixture(2), fixture(4), fixture(6), fixture(8), fixture(10))
        self.assertEqual(rows[1]['m1_pro']['total'], 20)
        changed = fixture(10)
        changed['metadata']['import_method'] = 'copy'
        with self.assertRaises(ValueError):
            combined(fixture(2), fixture(4), fixture(6), fixture(8), changed)


if __name__ == '__main__':
    unittest.main()
