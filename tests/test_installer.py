import importlib.util
from pathlib import Path
import tempfile
import unittest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parent.parent
installer = load('installer', ROOT / 'deploy/install.py')
helper = load('client_helper', ROOT / 'deploy/client_helper.py')


class InstallerTests(unittest.TestCase):
    def options(self, **overrides):
        options = dict(domain='vpn.example.com', port=1194, subnet='10.8.0.0/24',
                       interface='eth0', admin='admin', reverse_proxy=True)
        options.update(overrides)
        return options

    def test_rejects_config_injection_and_invalid_endpoints(self):
        for bad in ['vpn.example.com\nlog stdout', 'https://vpn.example.com', '192.0.2.1', '-bad.example.com', 'vpn.example.com/path']:
            with self.subTest(domain=bad), self.assertRaises(ValueError):
                installer.validate(self.options(domain=bad))
        with self.assertRaises(ValueError):
            installer.validate(self.options(interface='eth0"; flush ruleset'))
        for port in (0, 65536):
            with self.assertRaises(ValueError):
                installer.validate(self.options(port=port))

    def test_private_subnet_validation(self):
        for subnet in ('127.0.0.0/24', '203.0.113.0/24', '10.0.0.0/8', '10.8.0.1/24'):
            with self.subTest(subnet=subnet), self.assertRaises(ValueError):
                installer.validate(self.options(subnet=subnet))
        self.assertEqual(str(installer.validate(self.options(subnet='172.20.3.0/24'))), '172.20.3.0/24')

    def test_privileged_helper_accepts_only_two_known_arguments(self):
        self.assertEqual(helper.validate_args(['create', 'user.one']), ('create', 'user.one'))
        for arguments in ([], ['create'], ['shell', 'alice'], ['create', '../alice'],
                          ['revoke', 'alice\nkill bob'], ['create', '--help'], ['create', 'alice', 'extra']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                helper.validate_args(arguments)

    def test_rerun_preserves_existing_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'portal.env'
            installer.write_once(config, 'original-secret\n', 0o600)
            installer.write_once(config, 'replacement-secret\n', 0o600)
            self.assertEqual(config.read_text(), 'original-secret\n')
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_server_accepts_existing_profile_format(self):
        config = installer.server_config(self.options())
        self.assertIn('proto udp4\n', config)
        self.assertIn('management 127.0.0.1 7505\n', config)
        self.assertIn('AES-256-CBC', config)
        self.assertNotIn('tls-crypt', config)
        self.assertNotIn('auth-user-pass-verify', config)

    def test_caddy_package_default_is_replaced_only_during_initial_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'Caddyfile'
            config.write_text(':80 {\n    respond "package default"\n}\n')
            installer.configure_caddy(self.options(), config)
            self.assertIn('vpn.example.com {', config.read_text())
            self.assertIn('reverse_proxy 127.0.0.1:5000', config.read_text())
            config.write_text('# administrator configuration\n')
            installer.configure_caddy(self.options(completed=True), config)
            self.assertEqual(config.read_text(), '# administrator configuration\n')


if __name__ == '__main__':
    unittest.main()
