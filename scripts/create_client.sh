#!/bin/bash
set -euo pipefail
username=${1:?Username required}
[[ "$username" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$ ]] || { echo 'Invalid username' >&2; exit 1; }
exec 9>"${PKI_LOCK_PATH:-/run/openvpn-pki.lock}"
flock -w 90 9
cd "${EASYRSA_DIR:-/etc/openvpn/easy-rsa}"
# Never reassign an existing identity or silently reuse a revoked certificate.
if [[ -e "pki/issued/$username.crt" || -e "pki/private/$username.key" ]]; then
    echo 'Certificate identity already exists; administrator review required.' >&2
    exit 1
fi
EASYRSA_BATCH=1 ./easyrsa build-client-full "$username" nopass
test -s "pki/issued/$username.crt"
test -s "pki/private/$username.key"
openssl verify -CAfile pki/ca.crt "pki/issued/$username.crt"
