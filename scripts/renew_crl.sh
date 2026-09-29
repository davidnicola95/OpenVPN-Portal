#!/usr/bin/env bash
set -euo pipefail
umask 077
exec 9>"${PKI_LOCK_PATH:-/run/openvpn-pki.lock}"
flock -w 90 9
cd "${EASYRSA_DIR:-/etc/openvpn/easy-rsa}"
EASYRSA_BATCH=1 EASYRSA_CRL_DAYS=180 ./easyrsa gen-crl
openssl crl -in pki/crl.pem -noout -verify -CAfile pki/ca.crt
destination=${OPENVPN_DIR:-/etc/openvpn}
install -m 644 pki/crl.pem "$destination/crl.pem.new"
mv "$destination/crl.pem.new" "$destination/crl.pem"
