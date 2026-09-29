# Installation details

## Supported target

Use a fresh Debian 13 or Ubuntu 24.04 server with systemd. A VM/VPS is the simplest target. An LXC needs `/dev/net/tun` and sufficient host-granted permissions for network interfaces, nftables, and IPv4 forwarding; a restricted container will fail these requirements. Plain Docker/WSL is not supported by the native installer.

The DNS hostname must resolve to the intended server's public address. Forward TCP 80 and 443 and the selected OpenVPN UDP port to it. HTTPS and VPN use separate protocols; an HTTP reverse proxy does not forward the UDP VPN connection. If the server is behind CGNAT, inbound connectivity needs a reachable public address or a separate forwarding arrangement.

The generated portal backend binds to loopback. `--reverse-proxy` assumes your HTTPS proxy is on this host. Do not expose port 5000 or the management port 7505 to the Internet. For a remote proxy, use a separately secured transport and explicit host firewall policy.

## Network defaults

The installer selects the outbound interface from the IPv4 route to `1.1.1.1`; this lookup does not send a request. It creates a dedicated `ovpnportal` TUN interface and uses the chosen unused private client subnet. The VPN listener and generated profiles both use UDP. The generated server accepts the unchanged profiles, including AES-256-CBC compatibility, and negotiates GCM with clients that support it.

The new-server configuration pushes full-tunnel IPv4 routing and DNS servers `1.1.1.1`/`1.0.0.1`. IPv6 is routed into the VPN and blocked by OpenVPN to prevent it bypassing an IPv4-only tunnel; this is not an IPv6 Internet VPN. OS/client DNS behavior should be checked on each supported platform.

The installer adds only its own nftables tables. It does not flush other tables. Its initial firewall rules isolate VPN clients from the server, other VPN clients, and private/link-local network destinations; Internet-bound traffic is masqueraded through the selected interface. If LAN access is required, review `/etc/openvpn-portal/firewall.nft` and deliberately allow the exact destination subnets before the private-destination drop. Then run `sudo systemctl restart openvpn-portal-firewall`. Existing drop policies in other firewall tables still apply. Reapply this service if another firewall manager flushes the ruleset.

## Installed files

| Path | Purpose |
| --- | --- |
| `/opt/openvpn-portal` | Root-owned source, templates, scripts, and WSGI entry point. |
| `/var/lib/openvpn-portal/portal.env` | Unique session secret and existing-format admin credentials; service-user-owned, mode 0600. |
| `/var/lib/openvpn-portal/users.db` | Existing SQLite user schema; app-local state. |
| `/etc/openvpn/portal/easy-rsa` | Dedicated PKI. Root owns the CA and certificate operations; the web account can read issued client material but not the CA private key. |
| `/etc/openvpn/portal/crl.pem` | Root-published CRL readable after OpenVPN drops privileges. |
| `/etc/openvpn/server/portal.conf` | VPN service configuration. |
| `/etc/openvpn-portal` | Root-only installation settings and project firewall rules. |
| `/etc/sudoers.d/openvpn-portal` | Allows only the fixed, argument-validating installation helper. |
| `/root/openvpn-portal-credentials.txt` | Initial generated administrator credentials, mode 0600. |
| `/etc/caddy/Caddyfile` | HTTPS configuration, unless `--reverse-proxy` was selected. |

The portal's original password-change form continues to update its `.env`. The initial credentials file is not updated by that form; remove that initial file after securely recording/replacing the password. Never copy either file into Git or an issue report.

## Operations

```bash
sudo systemctl status openvpn-portal openvpn-server@portal caddy --no-pager
sudo journalctl -u openvpn-portal -u openvpn-server@portal --since '-15 minutes' --no-pager
curl --fail http://127.0.0.1:5000/login -o /dev/null
sudo systemctl list-timers openvpn-portal-crl.timer
```

Skip the Caddy service when using your own proxy. A successful HTTP login-page check is not a VPN reachability test. Verify registration, login, profile import, external tunnel connectivity, intended routing, and revocation with a disposable account. The original revocation behavior blocks future handshakes; use the existing Disconnect action to terminate an active session immediately.

For HTTPS failures, check DNS, TCP 80/443 forwarding, conflicting listeners, and `journalctl -u caddy`. For certificate-operation failures, inspect the portal log and exact PKI identity before retrying. An existing certificate name is never silently reused. For tunnels, check UDP forwarding, the client log, server log, system clock, and `sudo nft list ruleset`.

The CA lasts according to the installed Easy-RSA defaults; this installer creates an 825-day server certificate. Monitor and plan certificate renewal separately. The daily CRL timer renews the revocation list with the same PKI lock used by issuance/revocation. It does not rotate the CA or restart VPN sessions.
