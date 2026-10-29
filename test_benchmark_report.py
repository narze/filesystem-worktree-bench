import unittest

from benchmark_report import drive_for_target


class HardwareReportTests(unittest.TestCase):
    def test_selects_benchmark_drive_through_luks_not_the_other_disk(self):
        inventory = {'system': 'Linux', 'filesystem': {'filesystems': [
            {'source': '/dev/mapper/root[/@home]', 'fstype': 'btrfs'}]},
            'block_devices': {'blockdevices': [
                {'name': 'sda', 'type': 'disk', 'model': 'other', 'size': 250, 'rota': False, 'tran': 'sata'},
                {'name': 'nvme0n1', 'type': 'disk', 'model': 'benchmark SSD', 'size': 1000,
                 'rota': False, 'tran': 'nvme', 'children': [
                     {'name': 'nvme0n1p1', 'type': 'part', 'children': [
                         {'name': 'root', 'type': 'crypt'}]}]}]}}
        drive = drive_for_target(inventory)
        self.assertEqual(drive['model'], 'benchmark SSD')
        self.assertEqual(drive['encryption'], 'LUKS / dm-crypt')

    def test_mac_uses_physical_capacity_not_shared_apfs_volume_size(self):
        inventory = {'system': 'Darwin', 'physical_disk': {'MediaName': 'Apple SSD',
                     'TotalSize': 1000, 'BusProtocol': 'Apple Fabric'},
                     'filesystem': {'TotalSize': 800, 'FileVault': True}}
        drive = drive_for_target(inventory)
        self.assertEqual(drive['size_bytes'], 1000)
        self.assertEqual(drive['encryption'], 'FileVault / APFS')


if __name__ == '__main__':
    unittest.main()
