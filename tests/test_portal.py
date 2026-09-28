"""Run with python -m unittest discover -s tests -v. Never uses production PKI."""
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ['FLASK_SECRET_KEY']='test-only-session-secret-not-for-deployment-123456'
os.environ['ADMIN_USERNAME']='testadmin'
os.environ['ADMIN_PASSWORD']='Test-only-password!'
os.environ['COOKIE_SECURE']='false'
os.environ['NTFY_URL']=''
import app as portal

STATUS='''OpenVPN CLIENT LIST
Updated,Sun Sep 27 2026
Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
alice,203.0.113.10:43210,1000,2000,Sun Sep 27 12:00:00 2026
ROUTING TABLE
Virtual Address,Common Name,Real Address,Last Ref
10.8.0.2,alice,203.0.113.10:43210,Sun Sep 27 12:10:00 2026
GLOBAL STATS
Max bcast/mcast queue length,0
END
'''

class PortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        portal.DATABASE=str(self.root/'users.db'); portal.ENV_FILE=self.root/'.env'
        portal.ENV_FILE.write_text("ADMIN_PASSWORD='Test-only-password!'\n")
        portal.EASYRSA_DIR=str(self.root/'easy-rsa'); portal.NTFY_URL=''
        portal.VPN_PRIMARY_HOST='vpn.example.com';portal.VPN_BACKUP_HOST='vpn-backup.example.com';portal.VPN_PUBLIC_PORT=42873
        portal.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        portal.init_db(); self.client=portal.app.test_client()
        with portal.database() as conn:
            conn.execute('INSERT INTO users (username,password) VALUES (?,?)',('alice',portal.generate_password_hash('User-password!')))
        pki=Path(portal.EASYRSA_DIR)/'pki'
        (pki/'issued').mkdir(parents=True);(pki/'private').mkdir()
        (pki/'ca.crt').write_text('FIXTURE CA')
        (pki/'issued/alice.crt').write_text('FIXTURE CERT')
        (pki/'private/alice.key').write_text('FIXTURE KEY')
        self.mgmt=patch.object(portal,'management_command',return_value=STATUS);self.mgmt.start()
    def tearDown(self):
        self.mgmt.stop();self.tmp.cleanup()
    def post(self,path,data=None):
        self.client.get('/login')
        with self.client.session_transaction() as sess: token=sess['_csrf']
        return self.client.post(path,data={'csrf_token':token,**(data or {})})
    def admin(self):
        return self.post('/admin/login',{'username':'testadmin','password':'Test-only-password!'})
    def user(self):
        return self.post('/login',{'username':'alice','password':'User-password!'})
    def test_public_pages_render(self):
        for path in ['/','/login','/register','/admin/login']:
            result=self.client.get(path);self.assertEqual(result.status_code,200);self.assertIn(b'csrf_token',result.data)
    def test_protected_routes_redirect(self):
        for path in ['/dashboard','/download','/admin/dashboard']:
            self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.post('/admin/delete/1').status_code,302)
    def test_csrf_rejects_missing_invalid_and_unicode(self):
        self.assertEqual(self.client.post('/login',data={}).status_code,400)
        self.assertEqual(self.client.post('/login',data={'csrf_token':'é'}).status_code,400)
    def test_user_login_and_profile_preserved(self):
        self.assertEqual(self.user().status_code,302)
        self.assertIn(b'My connection',self.client.get('/dashboard').data)
        response=self.client.get('/download')
        self.assertEqual(response.status_code,200)
        for value in [b'remote vpn.example.com 42873',b'remote vpn-backup.example.com 42873',b'server-poll-timeout 10',b'FIXTURE KEY',b'remote-cert-tls server']:
            self.assertIn(value,response.data)
        self.assertIn('alice.ovpn',response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')
    def test_bad_credentials_and_unicode(self):
        self.assertEqual(self.post('/login',{'username':'alice','password':'bad'}).status_code,401)
        self.assertEqual(self.post('/admin/login',{'username':'é','password':'é'}).status_code,401)
    def test_user_cannot_manage_users(self):
        self.user()
        self.assertEqual(self.post('/admin/delete/1').status_code,302)
        with portal.database() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0],1)
    def test_switching_role_clears_old_role(self):
        self.admin(); self.user()
        with self.client.session_transaction() as sess:self.assertNotIn('admin_logged_in',sess)
    def test_registration_success(self):
        with patch.object(portal.subprocess,'run') as run:
            response=self.post('/register',{'username':'newuser','password':'New-password!','password2':'New-password!'})
        self.assertEqual(response.status_code,200);self.assertIn(b'Welcome aboard',response.data)
        self.assertEqual(run.call_count,1)
        with portal.database() as conn:self.assertIsNotNone(conn.execute('SELECT id FROM users WHERE username="newuser"').fetchone())
    def test_registration_validation_and_duplicates(self):
        with patch.object(portal.subprocess,'run') as run:
            for name,pw,pw2,code in [('../bad','Long-password!','Long-password!',400),('valid','short','short',400),('valid','Long-password!','different',400),('alice','Long-password!','Long-password!',409)]:
                self.assertEqual(self.post('/register',dict(username=name,password=pw,password2=pw2)).status_code,code)
            run.assert_not_called()
    def test_failed_provision_does_not_create_account(self):
        with patch.object(portal.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'fixture')):
            response=self.post('/register',dict(username='newuser',password='Long-password!',password2='Long-password!'))
        self.assertEqual(response.status_code,503)
        with portal.database() as conn:self.assertIsNone(conn.execute('SELECT id FROM users WHERE username="newuser"').fetchone())
    def test_management_parse_and_dashboard(self):
        self.assertEqual(portal.parse_vpn_status(STATUS)[0]['virtual_addr'],'10.8.0.2')
        self.admin();response=self.client.get('/admin/dashboard')
        for value in [b'Network overview',b'alice',b'10.8.0.2',b'Current password']:self.assertIn(value,response.data)
    def test_management_unavailable_is_not_empty_success(self):
        self.admin()
        with patch.object(portal,'get_active_vpn_users',side_effect=OSError('fixture')):
            response=self.client.get('/admin/dashboard')
        self.assertIn(b'Session status is unavailable',response.data)
    def test_revoke_failure_retains_account(self):
        self.admin()
        with patch.object(portal.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'fixture')):
            self.assertEqual(self.post('/admin/delete/1').status_code,302)
        with portal.database() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0],1)
        self.assertIn(b'account has been retained',self.client.get('/admin/dashboard').data)
    def test_revoke_success_removes_account(self):
        self.admin()
        with patch.object(portal.subprocess,'run') as run:self.assertEqual(self.post('/admin/delete/1').status_code,302)
        self.assertIn('revoke_client.sh',run.call_args.args[0][0])
        with portal.database() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM users').fetchone()[0],0)
    def test_disconnect_reports_result(self):
        self.admin()
        with patch.object(portal,'management_command',return_value='SUCCESS: killed\n') as command:
            self.assertEqual(self.post('/admin/kill/alice').status_code,302)
            command.assert_called_once_with('kill alice')
        self.assertIn(b'Disconnected alice',self.client.get('/admin/dashboard').data)
    def test_password_change_requires_current_and_confirmation(self):
        self.admin()
        self.post('/admin/change_password',dict(current_password='bad',new_password='Updated-password!',confirm_password='Updated-password!'))
        self.assertEqual(portal.admin_password(),'Test-only-password!')
        self.post('/admin/change_password',dict(current_password='Test-only-password!',new_password='Updated-password!',confirm_password='Updated-password!'))
        self.assertEqual(portal.admin_password(),'Updated-password!')
        self.assertIn(b'alice',self.client.get('/admin/dashboard').data)
        self.client.get('/admin/logout')
        self.assertEqual(self.post('/admin/login',dict(username='testadmin',password='Updated-password!')).status_code,302)
    def test_missing_profile_graceful(self):
        self.user();(Path(portal.EASYRSA_DIR)/'pki/private/alice.key').unlink()
        self.assertEqual(self.client.get('/download').status_code,503)
    def test_deleted_account_loses_existing_portal_session(self):
        self.user()
        with portal.database() as conn:conn.execute('DELETE FROM users WHERE username="alice"')
        self.assertEqual(self.client.get('/download').status_code,302)
        with self.client.session_transaction() as sess:self.assertNotIn('username',sess)
    def test_security_headers_and_static(self):
        response=self.client.get('/')
        self.assertEqual(response.headers['X-Frame-Options'],'DENY')
        for path in ['/static/portal.css','/static/portal.js','/static/mark.svg']:
            with self.client.get(path) as result:self.assertEqual(result.status_code,200)
    def test_path_and_command_injection_rejected(self):
        for name in ['../alice','alice\nkill other','x/y','x\\y']:
            self.assertFalse(portal.safe_common_name(name))
            with self.assertRaises(ValueError):portal.build_ovpn_file(name)

if __name__=='__main__':unittest.main()
