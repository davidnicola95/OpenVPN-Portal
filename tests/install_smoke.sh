#!/usr/bin/env bash
# Destructive only to its dedicated GitHub Actions runner. Never run on production.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true ]] || { echo 'Use the isolated GitHub Actions workflow.' >&2; exit 1; }
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
proxy_options=(--reverse-proxy)
if [[ ${CI_HTTPS_MODE:-external-proxy} == caddy ]]; then proxy_options=(); fi
bash install.sh --domain vpn.example.com "${proxy_options[@]}" --port 11940 --subnet 10.250.77.0/24
if [[ ${CI_HTTPS_MODE:-external-proxy} == caddy ]]; then
    caddy validate --config /etc/caddy/Caddyfile
    grep -q '^vpn.example.com {' /etc/caddy/Caddyfile
    [[ $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: vpn.example.com' http://127.0.0.1/login) == 308 ]]
    sha256sum /etc/caddy/Caddyfile > /tmp/portal-caddy.before
    echo 'PASS: packaged Caddy default replaced, valid HTTPS configuration, and HTTP redirect'
fi
install -m 0644 tests/installed_portal_smoke.py /tmp/installed_portal_smoke.py
runuser -u ovpnportal -- env PORTAL_ENV_FILE=/var/lib/openvpn-portal/portal.env \
    python3 /tmp/installed_portal_smoke.py issue
ip netns add portal-client
cleanup() {
    if [[ -f /tmp/portal-client.pid ]]; then kill "$(cat /tmp/portal-client.pid)" 2>/dev/null || true; fi
    ip netns del portal-client 2>/dev/null || true
    ip link del vp-testhost 2>/dev/null || true
}
trap cleanup EXIT
ip link add vp-testhost type veth peer name vp-testns
ip link set vp-testns netns portal-client
ip addr add 172.30.250.1/30 dev vp-testhost
ip link set vp-testhost up
ip -n portal-client addr add 172.30.250.2/30 dev vp-testns
ip -n portal-client link set vp-testns up
ip -n portal-client link set lo up
sed 's/remote vpn.example.com 11940/remote 172.30.250.1 11940/' \
    /var/lib/openvpn-portal/installer-smoke.ovpn > /tmp/portal-client.ovpn
chmod 600 /tmp/portal-client.ovpn
ip netns exec portal-client openvpn --config /tmp/portal-client.ovpn --route-nopull \
    --daemon --writepid /tmp/portal-client.pid --log /tmp/portal-client.log
connected=false
for attempt in {1..30}; do
    if grep -q 'Initialization Sequence Completed' /tmp/portal-client.log; then connected=true; break; fi
    sleep 1
done
if [[ $connected != true ]]; then cat /tmp/portal-client.log; exit 1; fi
echo 'PASS: real OpenVPN client/server TLS handshake in a separate network namespace'
cp /etc/openvpn/portal/easy-rsa/pki/issued/smokeclient.crt /tmp/issued-smokeclient.crt
runuser -u ovpnportal -- env PORTAL_ENV_FILE=/var/lib/openvpn-portal/portal.env \
    python3 /tmp/installed_portal_smoke.py revoke
if openssl verify -crl_check -CAfile /etc/openvpn/portal/ca.crt \
    -CRLfile /etc/openvpn/portal/crl.pem /tmp/issued-smokeclient.crt > /tmp/revocation-check.txt 2>&1; then
    echo 'Revoked certificate unexpectedly verified' >&2; exit 1
fi
grep -q 'certificate revoked' /tmp/revocation-check.txt
sha256sum /etc/openvpn/portal/easy-rsa/pki/private/ca.key /etc/openvpn/portal/server.key \
    /var/lib/openvpn-portal/portal.env /etc/openvpn/server/portal.conf > /tmp/portal-identities.before
vpn_pid=$(systemctl show -p MainPID --value openvpn-server@portal)
bash install.sh
sha256sum --check /tmp/portal-identities.before
if [[ ${CI_HTTPS_MODE:-external-proxy} == caddy ]]; then sha256sum --check /tmp/portal-caddy.before; fi
[[ $(systemctl show -p MainPID --value openvpn-server@portal) == "$vpn_pid" ]]
systemctl start openvpn-portal-crl.service
systemctl is-active --quiet openvpn-portal openvpn-server@portal
echo 'PASS: rerun preserved credentials, CA, server identity, settings, and running VPN process'
