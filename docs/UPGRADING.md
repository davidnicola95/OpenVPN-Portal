# Existing deployments and upgrades

The automated installer is for fresh servers or installations it previously created. It refuses an unrecognized existing OpenVPN configuration or PKI. Do not remove this check or move an existing CA aside to make the installer continue.

For an existing manually deployed portal, the application, templates, static assets, original certificate helpers, requirements file, and sample environment remain unchanged by this release. Continue using that deployment's service, configuration, database, CA, and VPN server. Installing this project's new server layout over a live independent VPN is not an automatic migration path.

## Back up an installer-managed deployment

Protect copies of `/var/lib/openvpn-portal`, `/etc/openvpn/portal`, `/etc/openvpn/server/portal.conf`, `/etc/openvpn-portal`, `/etc/caddy/Caddyfile` when used, and the application commit/release identifier. Use SQLite's backup API or stop the portal briefly when copying its database. These backups contain passwords and private keys; keep them encrypted and outside Git.

Run `git pull --ff-only` and `sudo bash install.sh` in the checkout. The installer preserves generated credentials, CA, keys, database, and administrator-edited configuration. It replaces application/deployment code and service units and restarts only the portal. The already-running VPN is left running. A failed installation can be resumed by rerunning with the same settings; inspect the error first. Missing identity files in a previously completed installation require backup recovery, not automatic regeneration.

Changing hostname, subnet, VPN port, or proxy mode requires an explicit configuration change and corresponding profile/network review. The installer rejects conflicting command-line settings on reruns. Changing a DNS address behind an unchanged hostname does not require new client profiles.

For rollback, restore the previous application/deployment code and service units, run `systemctl daemon-reload`, and restart the portal. Do not restore an old database or PKI over valid subsequent registrations or revocations. Reconcile these separately so revoked access is not accidentally restored.
