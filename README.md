# OpenVPN access portal

A Flask portal for an existing OpenVPN and Easy-RSA installation. Responsive user and administrator interfaces, personal profile downloads, account registration, session inspection, targeted disconnection, certificate revocation, and administrator password management.

## What is included

- `app.py`: existing route-compatible Flask application and management-interface integration.
- `templates/` and `static/`: self-hosted UI, with no CDN dependencies.
- `scripts/`: serialized Easy-RSA issuance and revocation helpers.
- `tests/`: isolated regression tests using disposable databases and mocked PKI operations.
- `.env.example`: deployment settings without secrets or real network identifiers.

This source does not include a user database, CA, private keys, client profiles, credentials, or a production `.env`. Do not add those files to Git. This is a portal application, not an automated installer for a new CA, VPN server, router, or DDNS system.

## Deployment assumptions

Python 3, Flask, Werkzeug and python-dotenv; Linux, Bash, flock, OpenSSL, and an initialized Easy-RSA installation. OpenVPN's management socket must be reachable locally (default `127.0.0.1:7505`) and provide the standard `status` response. Never expose this socket publicly.

The compatibility requirements match the existing Debian deployment. Review maintained package versions and security updates before distributing a new production installation. The application entry point disables debug mode; use a production WSGI service for a new deployment, and a least-privilege certificate-operation design where feasible. Login rate limiting and a privileged-operation broker remain future hardening work.

1. Place the source in an application directory and install `requirements.txt` in a virtual environment.
2. Copy `.env.example` to `.env`, make it readable only by the service account, and supply an admin username and strong password.
3. Generate a unique Flask secret, for example with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`, and set `FLASK_SECRET_KEY`.
4. Set `VPN_PRIMARY_HOST`, optional `VPN_BACKUP_HOST`, and `VPN_PUBLIC_PORT` to the existing public UDP endpoints. These settings generate profiles; they do not change OpenVPN's server listener or router NAT.
5. Point `EASYRSA_DIR`, `OPENVPN_DIR`, and optionally `DATABASE_PATH` and `SCRIPTS_DIR` at the intended files. Make helper scripts executable. These helpers need permissions to modify PKI and install the CRL; they are not suitable for an unprivileged account without an explicit privilege arrangement.
6. Preserve the current database and PKI when upgrading. Do not initialize or replace an existing CA. Run `init_db()` only to create the portal table if missing; it does not create the PKI.
7. Serve behind HTTPS. `COOKIE_SECURE=true` is the default. Set it false only for isolated local HTTP development. Choose a listener address accessible to your reverse proxy; do not publish the backend directly.

Run tests with `python3 -m unittest discover -s tests -v`. The Python tests mock certificate execution; validate the shell helpers in an isolated Linux environment before a new production installation.

## Routes and behavior

| Route | Function |
|---|---|
| `/` or `/login` | User sign-in |
| `/register` | Public self-service account and certificate creation |
| `/dashboard` | Personal profile download and setup guidance |
| `/download` | In-memory `.ovpn` attachment, never a shared temporary key file |
| `/admin/login` | Administrator sign-in |
| `/admin/dashboard` | Accounts, session snapshot, password settings |
| `/admin/delete/<id>` | POST: revoke certificate, then remove account |
| `/admin/kill/<common_name>` | POST: disconnect an individual common name |
| `/admin/change_password` | POST: verify current password, persist replacement |

All POST forms use a session-bound CSRF token. Sessions are cleared when switching login roles. Downloads and authenticated pages are not cacheable. Existing user password hashes and the SQLite schema are preserved. New registrations require 12-character passwords and safe certificate names. Public registration is inherited behavior; deployments that need administrator-only enrollment should restrict it explicitly.

Revocation updates a verified 180-day CRL atomically with mode 644 so the privilege-dropped OpenVPN process can read it. It does not restart OpenVPN or disconnect all clients. Disconnect an existing session explicitly if immediate termination is required. If a helper fails, the portal retains the account for investigation. An existing PKI identity is never silently reused during registration; partial provisioning needs administrator review. All certificate writers and CRL renewal jobs should share `PKI_LOCK_PATH`.

The admin page distinguishes zero sessions from an unavailable management interface. It is a snapshot at page load, not a continuously updating health monitor. A management connection does not prove Internet VPN reachability.

## Deployment verification and rollback

Before an upgrade, back up application source, `.env`, SQLite via its backup API, and the existing PKI/configuration to a protected server-local location. Record VPN and DDNS process state. Stage and test the release before replacing application files. Restart only the portal service; a UI deployment does not require a VPN restart, certificate regeneration, or router changes.

After deployment, verify public pages and static assets, both login roles, profile contents and both remote entries, management status, and the unchanged database/PKI fingerprints. Test issuing/revoking only with disposable fixture data unless an actual account operation was authorized. Confirm an external VPN connection separately when changing transport configuration.

Rollback by restoring application files and `.env` from the pre-deployment backup and restarting the portal service. Do not restore an old user database or PKI over legitimate new registrations or revocations; reconcile those separately. A new Flask secret invalidates prior portal sessions, but does not alter VPN certificates or existing tunnels.

## Configuration updates

Most environment changes take effect after restarting the portal. Administrator password changes are read from `.env` on each admin login. DDNS remains a separate service; this portal only embeds configured DNS hostnames into client profiles.
