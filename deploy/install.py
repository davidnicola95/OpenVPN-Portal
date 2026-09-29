#!/usr/bin/env python3
"""Fresh-host installer. Never imports or sources an existing deployment's .env as root."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent.parent
APP = Path('/opt/openvpn-portal')
STATE = Path('/var/lib/openvpn-portal')
CONTROL = Path('/etc/openvpn-portal')
MARKER = CONTROL / 'installation.json'
VPN_CONFIG = Path('/etc/openvpn/server/portal.conf')
VPN_DATA = Path('/etc/openvpn/portal')
SERVICE_USER = 'ovpnportal'


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, text=True, **kwargs)


def fail(message):
    raise SystemExit(message)


def validate(options):
    host = options['domain']
    if not isinstance(host, str) or len(host) > 253 or '.' not in host or any(
        not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
        for part in host.split('.')
    ):
        raise ValueError('Use a public DNS hostname, without https://, a path, or a port.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Use a DNS hostname; automatic HTTPS needs a domain you control.')
    if not 1024 <= int(options['port']) <= 65535:
        raise ValueError('VPN UDP port must be 1024–65535.')
    network = ipaddress.IPv4Network(options['subnet'])
    private_ranges = [ipaddress.IPv4Network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    if not any(network.subnet_of(value) for value in private_ranges) or not 24 <= network.prefixlen <= 27:
        raise ValueError('Use a private IPv4 /24 through /27 subnet dedicated to VPN clients.')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', options['interface']):
        raise ValueError('Invalid outbound interface name.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,63}', options['admin']):
        raise ValueError('Admin username must be 3–64 letters, digits, dots, underscores or hyphens.')
    return network


def write(path, text, mode=0o644, owner=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.installer-', delete=False) as output:
        output.write(text)
        os.fchmod(output.fileno(), mode)
        if owner:
            user = pwd.getpwnam(owner)
            os.fchown(output.fileno(), user.pw_uid, user.pw_gid)
    os.replace(output.name, path)


def write_once(path, text, mode=0o644):
    if not Path(path).exists():
        write(path, text, mode)


def configure_caddy(options, path=Path('/etc/caddy/Caddyfile')):
    config = f"{options['domain']} {{\n    reverse_proxy 127.0.0.1:5000 {{\n        transport http {{\n            response_header_timeout 180s\n        }}\n    }}\n}}\n"
    # The package creates a default Caddyfile during apt installation. Replace
    # that default on initial setup, then preserve administrator edits on reruns.
    if options.get('completed'):
        write_once(path, config)
    else:
        write(path, config)


def server_config(options):
    network = validate(options)
    return f'''port {options['port']}
proto udp4
dev ovpnportal
dev-type tun
topology subnet
server {network.network_address} {network.netmask}
ca /etc/openvpn/portal/ca.crt
cert /etc/openvpn/portal/server.crt
key /etc/openvpn/portal/server.key
dh none
tls-version-min 1.2
remote-cert-tls client
verify-client-cert require
crl-verify /etc/openvpn/portal/crl.pem
data-ciphers AES-256-GCM:AES-128-GCM:AES-256-CBC
data-ciphers-fallback AES-256-CBC
auth SHA256
allow-compression no
keepalive 10 120
persist-key
persist-tun
user nobody
group nogroup
management 127.0.0.1 7505
push "redirect-gateway def1 ipv6"
push "ifconfig-ipv6 fd15:53b6:dead::2/64 fd15:53b6:dead::1"
block-ipv6
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 1.0.0.1"
explicit-exit-notify 1
verb 3
'''


def firewall_config(options):
    network = validate(options)
    interface = options['interface']
    return f'''# Only project-owned tables. Existing firewall tables are never flushed.
table ip openvpn_portal_nat {{
  chain postrouting {{
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr {network} oifname "{interface}" masquerade
  }}
}}
table inet openvpn_portal_filter {{
  chain input {{
    type filter hook input priority -10; policy accept;
    iifname "ovpnportal" drop
  }}
  chain forward {{
    type filter hook forward priority -10; policy accept;
    iifname "ovpnportal" ip daddr {{ 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 }} drop
    iifname "ovpnportal" ip saddr {network} oifname "{interface}" accept
    iifname "ovpnportal" drop
    oifname "ovpnportal" ct state established,related accept
    oifname "ovpnportal" drop
  }}
}}
'''


def preflight(options, existing):
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    platform = (os_release.get('ID', '').strip('"'), os_release.get('VERSION_ID', '').strip('"'))
    if platform not in (('debian', '13'), ('ubuntu', '24.04')):
        fail('Supported systems: Debian 13 and Ubuntu 24.04. Use a fresh VM/VPS.')
    if not Path('/run/systemd/system').is_dir():
        fail('A running systemd host is required. Plain Docker/WSL environments are not supported.')
    if not Path('/dev/net/tun').is_char_device():
        fail('/dev/net/tun is missing. Enable TUN on your VM/LXC host before installation.')
    if not Path('/proc/sys/net/ipv4/ip_forward').exists():
        fail('IPv4 forwarding is unavailable on this host.')
    network = validate(options)
    if not Path('/sys/class/net', options['interface']).exists():
        fail('The selected outbound network interface does not exist.')
    if not existing:
        conflicts = list(Path('/etc/openvpn').glob('*.conf')) + list(Path('/etc/openvpn/server').glob('*.conf'))
        if conflicts or Path('/etc/openvpn/easy-rsa/pki').exists() or STATE.exists() or VPN_DATA.exists():
            fail('Existing OpenVPN configuration or portal state found. This fresh-host installer will not replace it. See docs/UPGRADING.md.')
        if APP.exists() and any(APP.iterdir()):
            fail('/opt/openvpn-portal already contains files without an installation marker; refusing to overwrite.')
        if not options['reverse_proxy'] and Path('/etc/caddy/Caddyfile').exists():
            fail('An existing Caddy configuration was found. Use a fresh host or --reverse-proxy.')
        if shutil.which('ufw') and 'Status: active' in run('ufw', 'status', capture_output=True).stdout:
            fail('UFW is active. This fresh-host installer does not replace another firewall.')
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'firewalld']).returncode == 0:
            fail('firewalld is active. This fresh-host installer does not replace another firewall.')
        routes = json.loads(run('ip', '-j', '-4', 'route', 'show', capture_output=True).stdout)
        for route in routes:
            destination = route.get('dst', 'default')
            if destination != 'default' and network.overlaps(ipaddress.IPv4Network(destination, strict=False)):
                fail(f'VPN subnet overlaps the host route {destination}; choose --subnet with an unused private network.')
        ports = [(options['port'], socket.SOCK_DGRAM), (5000, socket.SOCK_STREAM), (7505, socket.SOCK_STREAM)]
        if not options['reverse_proxy']:
            ports += [(80, socket.SOCK_STREAM), (443, socket.SOCK_STREAM)]
        for port, kind in ports:
            with socket.socket(socket.AF_INET, kind) as probe:
                try:
                    probe.bind(('0.0.0.0', port))
                except OSError:
                    fail(f'Port {port} is already in use; installation stopped before changes.')


def install(options, existing):
    packages = ['openvpn', 'easy-rsa', 'python3-flask', 'python3-dotenv', 'gunicorn',
                'nftables', 'openssl', 'iproute2', 'curl', 'ca-certificates', 'sudo']
    if not options['reverse_proxy']:
        packages.append('caddy')
    run('apt-get', 'update')
    run('apt-get', 'install', '-y', *packages, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})
    try:
        account = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        run('useradd', '--system', '--user-group', '--home-dir', str(STATE), '--shell', '/usr/sbin/nologin', SERVICE_USER)
        account = pwd.getpwnam(SERVICE_USER)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    os.chown(STATE, account.pw_uid, account.pw_gid)
    CONTROL.mkdir(mode=0o700, parents=True, exist_ok=True)
    CONTROL.chmod(0o700)
    if not existing:
        write(MARKER, json.dumps(options, indent=2) + '\n', 0o600)
    APP.mkdir(mode=0o755, parents=True, exist_ok=True)
    for name in ('app.py', 'wsgi.py', 'requirements.txt', 'README.md', 'LICENSE'):
        shutil.copyfile(SOURCE / name, APP / name)
        (APP / name).chmod(0o644)
    for name in ('templates', 'static', 'scripts', 'deploy', 'docs'):
        shutil.copytree(SOURCE / name, APP / name, dirs_exist_ok=True)
    for script in (APP / 'scripts').glob('*.sh'):
        script.chmod(0o755)

    VPN_DATA.mkdir(mode=0o755, parents=True, exist_ok=True)
    VPN_DATA.chmod(0o755)  # The privilege-dropped VPN process must read crl.pem.
    easy = VPN_DATA / 'easy-rsa'
    if not easy.exists():
        shutil.copytree('/usr/share/easy-rsa', easy, symlinks=False)
    env = {**os.environ, 'EASYRSA_BATCH': '1', 'EASYRSA_ALGO': 'rsa', 'EASYRSA_KEY_SIZE': '2048',
           'EASYRSA_CERT_EXPIRE': '825', 'EASYRSA_CRL_DAYS': '180'}
    env.pop('EASYRSA_REQ_CN', None)

    def easyrsa(*args):
        command_env = {**env, 'EASYRSA_REQ_CN': 'OpenVPN Portal CA'} if args[0] == 'build-ca' else env
        run('./easyrsa', *args, cwd=easy, env=command_env)

    if not (easy / 'pki').exists():
        easyrsa('init-pki')
    if not (easy / 'pki/ca.crt').exists():
        easyrsa('build-ca', 'nopass')
    if not (easy / 'pki/issued/portal-server.crt').exists():
        easyrsa('build-server-full', 'portal-server', 'nopass')
    if not (easy / 'pki/crl.pem').exists():
        easyrsa('gen-crl')
    for directory in (easy, easy / 'pki', easy / 'pki/issued', easy / 'pki/private'):
        directory.chmod(0o750)
        os.chown(directory, 0, account.pw_gid)
    (easy / 'pki/ca.crt').chmod(0o644)
    (easy / 'pki/private/ca.key').chmod(0o600)
    write_once(VPN_DATA / 'crl.pem', (easy / 'pki/crl.pem').read_text())
    VPN_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    for source, destination, mode in [('pki/ca.crt', 'ca.crt', 0o644),
                                      ('pki/issued/portal-server.crt', 'server.crt', 0o644),
                                      ('pki/private/portal-server.key', 'server.key', 0o600)]:
        write_once(VPN_DATA / destination, (easy / source).read_text(), mode)

    write('/usr/local/libexec/openvpn-portal-client', (SOURCE / 'deploy/client_helper.py').read_text(), 0o755)
    write('/etc/sudoers.d/openvpn-portal', 'ovpnportal ALL=(root) NOPASSWD: /usr/local/libexec/openvpn-portal-client\n', 0o440)
    run('visudo', '-cf', '/etc/sudoers.d/openvpn-portal')
    for action, script in [('create', 'create_client.sh'), ('revoke', 'revoke_client.sh')]:
        write(APP / 'helpers' / script, f'#!/bin/sh\nset -eu\nexec /usr/bin/sudo -n /usr/local/libexec/openvpn-portal-client {action} "${{1:?Username required}}"\n', 0o755)

    environment = STATE / 'portal.env'
    if not environment.exists():
        password = secrets.token_urlsafe(24)
        values = dict(FLASK_SECRET_KEY=secrets.token_urlsafe(48), ADMIN_USERNAME=options['admin'],
                      ADMIN_PASSWORD=password, BRAND_NAME='OpenVPN Portal',
                      VPN_PRIMARY_HOST=options['domain'], VPN_BACKUP_HOST='', VPN_PUBLIC_PORT=str(options['port']),
                      EASYRSA_DIR=str(easy), OPENVPN_DIR=str(VPN_DATA),
                      PKI_LOCK_PATH='/run/openvpn-portal-pki.lock', DATABASE_PATH=str(STATE / 'users.db'),
                      SCRIPTS_DIR=str(APP / 'helpers'), OPENVPN_MANAGEMENT_HOST='127.0.0.1',
                      OPENVPN_MANAGEMENT_PORT='7505', COOKIE_SECURE='true', NTFY_URL='')
        write(environment, ''.join(f"{key}='{value}'\n" for key, value in values.items()), 0o600, SERVICE_USER)
        write('/root/openvpn-portal-credentials.txt', f"Portal: https://{options['domain']}/admin/login\nUsername: {options['admin']}\nPassword: {password}\n", 0o600)
    write_once(VPN_CONFIG, server_config(options), 0o600)
    write_once(CONTROL / 'firewall.nft', firewall_config(options), 0o600)
    write_once('/etc/sysctl.d/90-openvpn-portal.conf', 'net.ipv4.ip_forward=1\n')
    run('sysctl', '-w', 'net.ipv4.ip_forward=1')
    for filename in ('openvpn-portal.service', 'openvpn-portal-firewall.service',
                     'openvpn-portal-crl.service', 'openvpn-portal-crl.timer'):
        write(Path('/etc/systemd/system') / filename, (SOURCE / 'deploy' / filename).read_text())
    write('/etc/systemd/system/openvpn-server@portal.service.d/portal.conf',
          '[Unit]\nRequires=openvpn-portal-firewall.service\nAfter=openvpn-portal-firewall.service\n')
    if not options['reverse_proxy']:
        configure_caddy(options)
        run('caddy', 'validate', '--config', '/etc/caddy/Caddyfile')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', 'openvpn-portal-firewall', 'openvpn-server@portal', 'openvpn-portal', 'openvpn-portal-crl.timer')
    run('systemctl', 'reload-or-restart', 'openvpn-portal-firewall')
    run('systemctl', 'start', 'openvpn-server@portal')
    run('systemctl', 'restart', 'openvpn-portal')
    run('systemctl', 'start', 'openvpn-portal-crl.timer')
    if not options['reverse_proxy']:
        run('systemctl', 'enable', '--now', 'caddy')
        run('systemctl', 'reload', 'caddy')
    run('curl', '--fail', '--retry', '10', '--retry-connrefused', '--retry-delay', '1',
        '--max-time', '5', '--output', '/dev/null', 'http://127.0.0.1:5000/login')
    run('systemctl', 'is-active', '--quiet', 'openvpn-server@portal', 'openvpn-portal')
    write(MARKER, json.dumps({**options, 'completed': True}, indent=2) + '\n', 0o600)
    print(f"\nInstalled. Administrator login: https://{options['domain']}/admin/login")
    print('Initial credentials: sudo cat /root/openvpn-portal-credentials.txt')
    print(f"Allow/forward UDP {options['port']} and TCP 80/443 to this server. Cloud/router firewalls are not modified.")
    if options['reverse_proxy']:
        print('Configure your HTTPS proxy on this host to reach 127.0.0.1:5000 with a 180-second timeout.')
    else:
        print('Caddy obtains HTTPS certificates once public DNS and TCP 80/443 reach this host.')
    print('Use /register to create a disposable test user, download its profile, and test from an external network.')
    print('Existing self-service registration is unchanged: anyone who can access /register can create a VPN account.')


def main():
    parser = argparse.ArgumentParser(description='Install OpenVPN + Easy-RSA + the portal on a fresh Debian 13 or Ubuntu 24.04 server.')
    parser.add_argument('--domain', help='Public DNS hostname pointing to this server')
    parser.add_argument('--port', type=int, help='OpenVPN UDP port (default 1194)')
    parser.add_argument('--subnet', help='Unused private IPv4 client subnet (default 10.8.0.0/24)')
    parser.add_argument('--interface', help='Outbound interface (auto-detected from the IPv4 default route)')
    parser.add_argument('--admin', help='Administrator username (default admin)')
    parser.add_argument('--reverse-proxy', action='store_true', help='Use your own HTTPS proxy on this host; skip Caddy')
    args = parser.parse_args()
    if os.geteuid() != 0:
        fail('Run as root with sudo bash install.sh.')
    existing = MARKER.exists()
    if existing:
        options = json.loads(MARKER.read_text())
        if options.get('completed'):
            for required in (STATE / 'portal.env', VPN_DATA / 'easy-rsa/pki/ca.crt', VPN_DATA / 'easy-rsa/pki/private/ca.key'):
                if not required.exists():
                    fail(f'Existing installation is missing {required}; restore its backup instead of generating a new identity.')
        for key in ('domain', 'port', 'subnet', 'interface', 'admin'):
            supplied = getattr(args, key)
            if supplied is not None and supplied != options[key]:
                fail('An installation already exists with different settings. See docs/UPGRADING.md; credentials and PKI are preserved.')
        if args.reverse_proxy and not options['reverse_proxy']:
            fail('Cannot change HTTPS mode during a software upgrade. See docs/UPGRADING.md.')
    else:
        domain = args.domain
        if not domain:
            if not sys.stdin.isatty():
                fail('Pass --domain vpn.example.com for noninteractive installation.')
            domain = input('Public DNS hostname pointing to this server: ').strip()
        interface = args.interface
        if not interface:
            route = json.loads(run('ip', '-j', '-4', 'route', 'get', '1.1.1.1', capture_output=True).stdout)
            interface = route[0]['dev']
        options = dict(domain=domain, port=args.port if args.port is not None else 1194, subnet=args.subnet or '10.8.0.0/24',
                       interface=interface, admin=args.admin or 'admin', reverse_proxy=args.reverse_proxy)
    try:
        preflight(options, existing)
    except ValueError as error:
        fail(str(error))
    install(options, existing)


if __name__ == '__main__':
    main()
