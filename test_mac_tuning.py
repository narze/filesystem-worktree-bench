import unittest

from mac_tuning import validate_volume


class VolumeGuardTests(unittest.TestCase):
    def test_accepts_only_recorded_experiment_volume(self):
        expected = {'VolumeUUID': 'new-uuid', 'DeviceIdentifier': 'disk3s7',
                    'VolumeName': 'FSBenchTuning-test', 'MountPoint': '/Volumes/FSBenchTuning-test'}
        validate_volume(expected, 'new-uuid', 'FSBenchTuning-test')
        for key, value in [('VolumeUUID', 'data-uuid'), ('VolumeName', 'Data'),
                           ('MountPoint', '/System/Volumes/Data'), ('DeviceIdentifier', 'disk3')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_volume({**expected, key: value}, 'new-uuid', 'FSBenchTuning-test')

    def test_rejects_unencrypted_volume(self):
        from mac_tuning import require_encrypted
        for info in ({}, {'Encryption': False}):
            with self.assertRaises(ValueError):
                require_encrypted(info)
        require_encrypted({'Encryption': True})

    def test_cleanup_can_validate_locked_unmounted_volume(self):
        info = {'VolumeUUID': 'new-uuid', 'DeviceIdentifier': 'disk3s7',
                'VolumeName': 'FSBenchTuning-test'}
        with self.assertRaises(ValueError):
            validate_volume(info, 'new-uuid', 'FSBenchTuning-test')
        validate_volume(info, 'new-uuid', 'FSBenchTuning-test', allow_unmounted=True)
        with self.assertRaises(ValueError):
            validate_volume({**info, 'MountPoint': '/'}, 'new-uuid',
                            'FSBenchTuning-test', allow_unmounted=True)
