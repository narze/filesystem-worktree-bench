import json
from pathlib import Path
import tempfile
import unittest
from mac_tuning_report import build, cpu_seconds, event_history_files, process_cpu_totals, summarize, vm_counters


class ReportTests(unittest.TestCase):
    def test_vm_counters_preserve_page_units(self):
        text = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
                'Swapins: 100.\nSwapouts: 200.\nPageouts: 3.\n')
        self.assertEqual(vm_counters(text), {'page_size': 16384, 'Swapins': 100,
                                           'Swapouts': 200, 'Pageouts': 3})

    def test_event_history_ignores_marker_and_uuid(self):
        text = ('/Volumes/Test Volume/.fseventsd/000000000000abcd 1234 100\n'
                '/Volumes/Test Volume/.fseventsd/no_log 0 99\n'
                '/Volumes/Test Volume/.fseventsd/fseventsd-uuid 36 90\n')
        self.assertEqual(event_history_files(text), {'000000000000abcd': (1234, 100)})

    def test_cpu_time_formats_and_aggregation(self):
        self.assertAlmostEqual(cpu_seconds('12:03.50'), 723.5)
        self.assertEqual(cpu_seconds('1:02:03'), 3723)
        self.assertEqual(cpu_seconds('2-01:02:03'), 176523)
        text = ' PID PPID TIME %CPU RSS COMM\n 1 0 2:03.5 1.2 100 /usr/libexec/fseventsd\n 2 0 0:01.0 1 100 /usr/libexec/mdworker_shared\n 3 0 0:02.0 1 100 /usr/libexec/mdworker_shared\n'
        self.assertEqual(process_cpu_totals(text), {'fseventsd': 123.5, 'mdworker_shared': 3})

    def test_compares_matching_worker_counts(self):
        runs = {label: {'status': 'complete', 'samples': [
            {'workers': 1, 'total_seconds': n, 'checkout': {'batch_seconds': n / 4},
             'install': {'batch_seconds': n / 2}, 'delete': {'batch_seconds': n / 4}}
            for n in times]} for label, times in [('A', [10, 12, 11]), ('B', [5, 7, 6])]}
        result = summarize(runs)
        self.assertEqual(result['A']['1']['median_seconds'], 11)
        self.assertAlmostEqual(result['B']['1']['speedup_vs_A'], 11 / 6)
        self.assertEqual(result['B']['1']['samples'], 3)
        self.assertEqual(result['B']['1']['stage_medians']['install'], 3)

    def test_incomplete_run_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize({'A': {'status': 'failed', 'samples': []}})

    def test_report_cpu_interval_excludes_setup_and_first_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'A-results').mkdir()
            sample = {'workers': 1, 'total_seconds': 6,
                      **{s: {'batch_seconds': 2} for s in ('checkout', 'install', 'delete')}}
            (root / 'A-results/results.json').write_text(json.dumps({'status': 'complete', 'samples': [sample]}))
            (root / 'experiment.json').write_text(json.dumps({
                'conditions': [{'label': 'A', 'status': 'complete',
                                'resources_before': {'processes': 'raw snapshot'}}],
                'resources_before': {'processes': 'raw snapshot'},
                'free_before': 100, 'free_after': 100, 'volume_deleted': True}))
            records = [{'samples_completed': n, 'utc': f'2026-10-29T00:00:{n*10:02}+00:00',
                        'processes': f'PID PPID TIME %CPU RSS COMM\n1 0 0:{seconds:02}.0 1 1 /fseventsd\n'}
                       for n, seconds in [(0, 0), (1, 30), (2, 40)]]
            (root / 'A-resources.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
            (root / 'no-log-verification.json').write_text(json.dumps({'history_files_modified_over_10s_after_marker': 0}))
            output = root / 'report.html'
            result = build(root, output)
            cpu = result['scored_interval_daemon_cpu']['A']
            self.assertEqual(cpu['cpu_seconds_delta']['fseventsd'], 10)
            self.assertEqual(cpu['covered_samples'], 1)
            self.assertEqual(cpu['wall_seconds'], 10)
            self.assertTrue(output.is_file())
            self.assertEqual(result['no_log_verification']['history_files_modified_over_10s_after_marker'], 0)
            self.assertIn('metadata-only', output.read_text())
            self.assertNotIn('resources_before', result['experiment'])
            self.assertNotIn('resources_before', result['experiment']['conditions'][0])
            self.assertIn('raw snapshot', (root / 'experiment.json').read_text())
            self.assertIn('One sequential block per condition', output.read_text())
            self.assertIn('near-zero cumulative CPU', output.read_text())
            self.assertIn('no idle baseline', output.read_text())
