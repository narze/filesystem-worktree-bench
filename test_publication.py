import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from publication import audit_snapshot, sanitize_text


class PublicationTests(unittest.TestCase):
    def test_removes_private_addresses_and_keeps_public_references(self):
        private = 'https' + '://service.private.invalid/path?key=hidden'
        public = 'https' + '://docs.kernel.org/filesystems/xfs.html'
        host = 'host.risk-in.' + 'ts.net'
        address = '192.168.' + '1.8'
        data = private + ' ' + host + ' ' + address + ' ' + public
        result = sanitize_text(data)
        self.assertNotIn(private, result)
        self.assertNotIn(host, result)
        self.assertNotIn(address, result)
        self.assertIn(public, result)

    def test_removes_credentials_even_on_public_domains(self):
        urls = ['https' + '://user:password@github.com/repo',
                'https' + '://github.com/repo?access_token=hidden']
        for value in urls:
            with self.subTest(value=value):
                self.assertNotIn(value, sanitize_text(value))
        token = 'ghp_' + 'A' * 36
        self.assertNotIn(token, sanitize_text(token))

    def test_redacts_json_hostnames_and_secret_values_without_changing_measurements(self):
        data = {'hostname': 'private-machine', 'token': 'hidden',
                'metadata': {'pnpm_version': '11.18.0', 'total_seconds': 12.5},
                'install_scripts': False}
        result = json.loads(sanitize_text(json.dumps(data), is_json=True))
        self.assertEqual(result['hostname'], '[REDACTED]')
        self.assertEqual(result['token'], '[REDACTED]')
        self.assertEqual(result['metadata'], data['metadata'])
        self.assertFalse(result['install_scripts'])

    def test_audit_inspects_nested_zip_contents(self):
        import io
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, 'w') as archive:
                archive.writestr('private.txt', 'ghp_' + 'B' * 36)
            with zipfile.ZipFile(root / 'outer.zip', 'w') as archive:
                archive.writestr('inner.zip', inner.getvalue())
            with self.assertRaisesRegex(ValueError, 'inner.zip'):
                audit_snapshot(root)

    def test_audit_accepts_redacted_inventory_and_public_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'inventory.json').write_text('{"hostname": "[REDACTED]"}')
            (root / 'readme.txt').write_text('https' + '://docs.kernel.org/')
            self.assertEqual(audit_snapshot(root), 2)
