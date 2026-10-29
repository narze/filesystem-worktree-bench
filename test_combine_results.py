import unittest

from combine_results import combine
from test_compare import fixture


class CombinedResultTests(unittest.TestCase):
    def datasets(self):
        return {name: fixture(number) for number,name in enumerate(
            ('desktop','m4','thinkpad','debian','m1','native-btrfs','image-btrfs','image-xfs'),1)}

    def test_keeps_native_control_separate_from_older_desktop_run(self):
        combined=combine(self.datasets())
        self.assertEqual(len(combined['datasets']),8)
        self.assertEqual(combined['datasets']['desktop']['workers'][1]['median'],1)
        self.assertEqual(combined['datasets']['native-btrfs']['workers'][1]['median'],6)
        self.assertEqual(combined['successful_batches'],32)
        self.assertEqual(combined['measured_workflows'],48)

    def test_refuses_to_combine_an_incompatible_workload(self):
        data=self.datasets();data['image-xfs']['metadata']['commit']='other'
        with self.assertRaises(ValueError):combine(data)

    def test_keeps_failed_attempts_distinct_from_successful_timings(self):
        data=self.datasets();data['m4']['discarded_attempts']=[{'error':'checkout failed'}]
        combined=combine(data)
        self.assertEqual(combined['failed_attempts'],1)
        self.assertEqual(combined['datasets']['m4']['successful_batches'],4)


if __name__=='__main__':unittest.main()
