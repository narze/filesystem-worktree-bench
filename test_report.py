import unittest

from report import render


class ReportTests(unittest.TestCase):
    def test_reports_batch_time_and_throughput_for_variable_work(self):
        result = {'status': 'complete', 'metadata': {'commit': 'abc', 'runs': 2},
                  'samples': [{'workers': workers, 'round': run, 'total_seconds': workers * 2,
                               'checkout': {'batch_seconds': workers},
                               'delete': {'batch_seconds': workers}}
                              for workers in (1, 2, 3, 4) for run in (1, 2)]}
        html = render(result)
        self.assertIn('0.50', html)
        self.assertIn('8.000', html)
        self.assertIn('workflows/s', html)
        self.assertIn('stage barriers', html)

    def test_rejects_incomplete_results(self):
        with self.assertRaises(ValueError):
            render({'status': 'failed', 'samples': []})


if __name__ == '__main__':
    unittest.main()
