# OpenVPN Portal

[![Installation verification](https://github.com/davidnicola95/OpenVPN-Portal/actions/workflows/install.yml/badge.svg)](https://github.com/davidnicola95/OpenVPN-Portal/actions/workflows/install.yml)

A Flask portal for OpenVPN and Easy-RSA: self-service registration, personal `.ovpn` downloads, user/admin sign-in, session inspection, targeted disconnection, certificate revocation, and administrator password management.

## Quick install

Use a **fresh Debian 13 or Ubuntu 24.04 VM/VPS** with root/sudo, systemd, IPv4 Internet access, and `/dev/net/tun`. Point a public DNS hostname you control at the server. Allow/forward **TCP 80/443** for HTTPS and **UDP 1194** for OpenVPN in your cloud firewall/router.

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/davidnicola95/OpenVPN-Portal.git
cd OpenVPN-Portal
sudo bash install.sh
```

The installer asks for the public hostname. It installs dependencies, creates a dedicated CA/server certificate, generates unique portal credentials, configures OpenVPN and routing, and starts the portal behind Caddy HTTPS. No manual `.env` editing is needed for a fresh default installation.

Read your generated administrator credentials:

```bash
sudo cat /root/openvpn-portal-credentials.txt
```

Open `https://YOUR-HOSTNAME/admin/login` for administration. Users create accounts at `/register`, sign in at `/login`, download their personal profile, and import it into OpenVPN Connect. The existing certificate-based VPN authentication remains unchanged; the portal password is for the website.

**Self-service registration is unchanged:** anyone who can reach `/register` can create a VPN account. Restrict portal access at your proxy/firewall if enrollment should be private. This update does not add approval, invitations, or a new authentication system.

## What the installer configures

- Distribution-packaged OpenVPN, Easy-RSA, Flask, python-dotenv, Gunicorn, nftables, and Caddy.
- The existing application and certificate scripts, without changing their contents.
- An unprivileged portal service; a narrowly scoped sudo helper runs the original issuance/revocation scripts. The web account cannot read the CA private key.
- UDP OpenVPN on port 1194, IPv4 clients on `10.8.0.0/24`, and NAT through the default-route interface.
- Internet access for VPN clients; generated firewall rules isolate clients from private networks and the server itself. Review [network setup](docs/INSTALLATION.md) if you need LAN access.
- A loopback-only web backend (`127.0.0.1:5000`) and management interface (`127.0.0.1:7505`).
- Automatic HTTPS once DNS and inbound TCP 80/443 reach the host, plus a daily CRL renewal timer.

Router NAT, cloud firewall rules, and DNS records remain administrator-controlled. A health check verifies local service startup; test a real client from an external network before sharing access.

## Installation options

```bash
sudo bash install.sh --domain vpn.example.com
sudo bash install.sh --domain vpn.example.com --port 42873 --subnet 10.23.40.0/24
sudo bash install.sh --domain vpn.example.com --reverse-proxy
```

`--reverse-proxy` skips Caddy for an existing HTTPS proxy **on the same host**, forwarding to `127.0.0.1:5000` with a 180-second upstream timeout. Other options are `--interface` and `--admin`. Run `sudo bash install.sh --help` for the full list.

This fresh-install path refuses existing OpenVPN configurations/PKI instead of replacing them. It also checks the OS, TUN, port conflicts, subnet overlap, and common existing firewall managers before changing the host. For an existing deployment, use [upgrade guidance](docs/UPGRADING.md).

## Update an installation created by this script

Back up the deployment first, then:

```bash
git pull --ff-only
sudo bash install.sh
```

Reruns preserve the existing CA, keys, database, portal credentials, OpenVPN configuration, firewall configuration, and Caddyfile. The portal restarts; an already-running VPN process is not restarted. Changing the installation's hostname/network is a separate administrative operation.

## Documentation and tests

- [Installation, network requirements, files, and troubleshooting](docs/INSTALLATION.md)
- [Existing deployments, backups, and updates](docs/UPGRADING.md)
- [Scope of this installation-only update](docs/INSTALLER_CHANGES.md)

```bash
python3 -m unittest discover -s tests -v
```

CI checks that the original core files remain unchanged, runs the existing regression tests with Debian 13 dependencies, and runs a fresh Ubuntu 24.04 installation. The installation test exercises real certificate issuance, profile download, a local OpenVPN handshake in a separate network namespace, revocation, and a second installer run. The destructive installation smoke test is restricted to disposable GitHub Actions runners.

No production database, `.env`, CA, private keys, client profiles, or deployment inventory belongs in this repository. MIT licensed; see [LICENSE](LICENSE).
