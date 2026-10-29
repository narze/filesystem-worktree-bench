import unittest
from pathlib import Path

from fs_experiment import measured_schedule, preallocate_image, require_image


class FilesystemExperimentTests(unittest.TestCase):
    def test_preallocation_restores_sparse_file_without_changing_contents(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'xfs.img'
            with image.open('wb') as f:
                f.write(b'filesystem metadata')
                f.truncate(16*2**20)
            self.assertLess(image.stat().st_blocks*512,image.stat().st_size)
            preallocate_image(image)
            self.assertGreaterEqual(image.stat().st_blocks*512,image.stat().st_size)
            with image.open('rb') as f:self.assertEqual(f.read(19),b'filesystem metadata')

    def test_schedule_pairs_every_filesystem_at_the_same_worker_count(self):
        schedule = measured_schedule(['native-btrfs', 'image-btrfs', 'image-xfs'], 10)
        self.assertEqual(len(schedule), 120)
        self.assertEqual(len(set(schedule)), 120)
        for offset in range(0, len(schedule), 3):
            group = schedule[offset:offset+3]
            self.assertEqual(len({(number, workers) for number, workers, _ in group}), 1)
            self.assertEqual({case for _, _, case in group}, {'native-btrfs','image-btrfs','image-xfs'})
        self.assertEqual(measured_schedule(['a','b'],2),measured_schedule(['a','b'],2))

    def test_format_target_must_be_our_regular_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            image=root/'xfs.img';image.touch()
            self.assertEqual(require_image(image,root),image)
            for path in (Path('/dev/sda'),root/'missing.img'):
                with self.assertRaises(ValueError):require_image(path,root)
            alias=root/'alias.img';alias.symlink_to(image)
            with self.assertRaises(ValueError):require_image(alias,root)


if __name__=='__main__':unittest.main()
