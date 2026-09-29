#!/usr/bin/python3
"""Installation adapter for the unchanged root-owned certificate scripts.

Only create/revoke with a validated certificate name are accepted. Paths and
environment are fixed here; no app-writable configuration is ever run as root.
"""
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys


def validate_args(arguments):
    if len(arguments) != 2 or arguments[0] not in ('create', 'revoke'):
        raise ValueError('Expected create|revoke and one username')
    action, username = arguments
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,63}', username):
        raise ValueError('Invalid username')
    return action, username


def main():
    try:
        action, username = validate_args(sys.argv[1:])
    except ValueError as error:
        raise SystemExit(str(error)) from None
    if os.geteuid() != 0:
        raise SystemExit('This helper must be invoked through its installation sudo rule')
    environment = {
        'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8',
        'EASYRSA_DIR': '/etc/openvpn/portal/easy-rsa',
        'OPENVPN_DIR': '/etc/openvpn/portal', 'PKI_LOCK_PATH': '/run/openvpn-portal-pki.lock',
    }
    os.umask(0o077)
    script = '/opt/openvpn-portal/scripts/' + ('create_client.sh' if action == 'create' else 'revoke_client.sh')
    subprocess.run(['/bin/bash', script, username], env=environment, check=True, timeout=115)
    if action == 'create':
        group = pwd.getpwnam('ovpnportal').pw_gid
        pki = Path(environment['EASYRSA_DIR']) / 'pki'
        for part, suffix in (('issued', '.crt'), ('private', '.key')):
            path = pki / part / (username + suffix)
            os.chown(path, 0, group)
            path.chmod(0o640)


if __name__ == '__main__':
    main()
