#!/bin/bash
set -euo pipefail
username=${1:?Username required}
[[ "$username" != */* && "$username" != *\\* && "$username" != *$'\n'* && "$username" != *$'\r'* && "$username" != '.' && "$username" != '..' ]] || exit 1
exec 9>"${PKI_LOCK_PATH:-/run/openvpn-pki.lock}"
flock -w 90 9
cd "${EASYRSA_DIR:-/etc/openvpn/easy-rsa}"
EASYRSA_BATCH=1 ./easyrsa revoke "$username"
EASYRSA_BATCH=1 EASYRSA_CRL_DAYS=180 ./easyrsa gen-crl
openssl crl -in pki/crl.pem -noout -verify -CAfile pki/ca.crt
openvpn_dir=${OPENVPN_DIR:-/etc/openvpn}
install -o root -g root -m 644 pki/crl.pem "$openvpn_dir/crl.pem.new"
mv "$openvpn_dir/crl.pem.new" "$openvpn_dir/crl.pem"
# OpenVPN checks the CRL on new handshakes. Do not restart every user's tunnel.
# An administrator can explicitly disconnect an existing session in the portal.
