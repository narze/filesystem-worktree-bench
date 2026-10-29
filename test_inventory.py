import unittest

from inventory import mac_device, select_fields


class InventoryTests(unittest.TestCase):
    def test_resolves_a_mac_subdirectory_to_its_volume_device(self):
        output = 'Filesystem 512-blocks Used Available Capacity Mounted on\n/dev/disk3s5 100 80 20 80% /System/Volumes/Data\n'
        self.assertEqual(mac_device(output), '/dev/disk3s5')
        self.assertIsNone(mac_device(''))

    def test_inventory_filter_drops_serial_numbers_and_identifiers(self):
        raw = {'_name': 'Apple SSD', 'size_in_bytes': 512000000000,
               'device_serial': 'private', 'platform_UUID': 'private',
               '_items': [{'_name': 'controller', 'link_speed': '8 GT/s',
                           'serial_number': 'private'}]}
        filtered = select_fields(raw, {'_name', 'size_in_bytes', 'link_speed', '_items'})
        self.assertEqual(filtered['_items'], [{'_name': 'controller', 'link_speed': '8 GT/s'}])
        self.assertNotIn('private', str(filtered))


if __name__ == '__main__':
    unittest.main()
