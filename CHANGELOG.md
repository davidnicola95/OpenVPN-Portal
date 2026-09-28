# Release notes

## Portal redesign September 2026

- Responsive sign-in and registration pages with separate user/admin navigation, labeled fields, password visibility controls, and self-hosted assets.
- Personal dashboard with profile download, setup steps, endpoint details, and credential-handling guidance.
- Admin overview with account search, actual session data, explicit unavailable states, and confirmation dialogs for revocation/disconnection.
- Session-bound CSRF tokens, secure cookies by default, a required random session secret, response security headers, and debug mode disabled.
- Existing SQLite schema and user password hashes retained; configurable VPN endpoints generate the same profile contents when configured to match the existing installation.
- Profile attachments built in memory; no new unencrypted client keys written to shared temporary files.
- Existing sessions for removed accounts cannot download profiles. Role changes clear the previous role's browser session.
- Admin password updates require the current password and confirmation, safely persist quoted values, and return to a refreshed dashboard.
- Certificate helpers propagate failures, serialize PKI changes, verify output, and publish readable CRLs atomically without restarting every VPN tunnel.

Validation: isolated Python regression tests cover authentication, CSRF, profile generation, management status, and failed certificate operations. Linux fixture checks cover helper success, failure propagation, invalid input, existing identities, and CRL permissions. Desktop and mobile browser checks cover the portal interfaces.
