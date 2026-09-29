# Installation-only update

The baseline is commit `0f80b46f6599cc59f6e8bd08239859ac51e394ee`.

Unchanged core files: `app.py`, all `templates/`, all `static/`, `scripts/create_client.sh`, `scripts/revoke_client.sh`, `.env.example`, `requirements.txt`, and the original `tests/test_portal.py`. CI compares these directly against the baseline commit.

This update adds:

- `install.sh` and `deploy/install.py`: fresh-host setup, validation, package installation, unique configuration, service setup, and repeat-run preservation.
- `wsgi.py`: calls the existing database initialization function and exports the existing Flask app for Gunicorn.
- Installation helpers and systemd units: permissions, restricted certificate-script invocation, forwarding/NAT, and CRL maintenance.
- Installer tests and CI: original regression suite, installer input validation, real disposable PKI/VPN integration, and preservation checks.
- Quickstart, operational/update documentation, and MIT license.

No route, screen, registration policy, authentication method, database schema, profile-generation function, or original certificate helper is modified. No live production VPN is deployed or changed by publishing these repository files.
