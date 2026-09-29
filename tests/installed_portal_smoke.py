"""Run only on the disposable CI installation, as ovpnportal. Exercises the unchanged app."""
import os
from pathlib import Path
import sys

sys.path.insert(0, '/opt/openvpn-portal')
import app as portal

portal.app.config['TESTING'] = True
client = portal.app.test_client()
base = 'https://vpn.example.com'


def post(path, values):
    client.get('/login', base_url=base)
    with client.session_transaction(base_url=base) as session:
        token = session['_csrf']
    return client.post(path, data={'csrf_token': token, **values}, base_url=base)


if sys.argv[1] == 'issue':
    response = post('/register', {'username': 'smokeclient', 'password': 'Disposable-test-password-123',
                                  'password2': 'Disposable-test-password-123'})
    assert response.status_code == 200, response.status_code
    assert post('/login', {'username': 'smokeclient', 'password': 'Disposable-test-password-123'}).status_code == 302
    profile = client.get('/download', base_url=base)
    assert profile.status_code == 200
    assert b'remote vpn.example.com 11940' in profile.data
    target = Path('/var/lib/openvpn-portal/installer-smoke.ovpn')
    target.write_bytes(profile.data)
    target.chmod(0o600)
    assert not os.access('/etc/openvpn/portal/easy-rsa/pki/private/ca.key', os.R_OK), 'Web user can read the CA private key'
    print('PASS: registration, real Easy-RSA issuance, login, and profile download')
elif sys.argv[1] == 'revoke':
    assert post('/admin/login', {'username': portal.ADMIN_USERNAME, 'password': portal.admin_password()}).status_code == 302
    with portal.database() as conn:
        user_id = conn.execute('SELECT id FROM users WHERE username=?', ('smokeclient',)).fetchone()[0]
    assert post(f'/admin/delete/{user_id}', {}).status_code == 302
    with portal.database() as conn:
        assert conn.execute('SELECT id FROM users WHERE username=?', ('smokeclient',)).fetchone() is None
    assert post('/admin/kill/smokeclient', {}).status_code == 302
    print('PASS: administrator login, real certificate revocation, and targeted disconnect')
else:
    raise SystemExit('Use issue or revoke')
