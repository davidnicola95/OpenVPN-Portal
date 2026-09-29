#!/usr/bin/env bash
set -euo pipefail
# Delete/recreate only our own tables in one atomic nft transaction.
batch=$(mktemp)
trap 'rm -f "$batch"' EXIT
for family_table in 'ip openvpn_portal_nat' 'inet openvpn_portal_filter'; do
    read -r family table <<< "$family_table"
    if nft list table "$family" "$table" >/dev/null 2>&1; then
        printf 'delete table %s %s\n' "$family" "$table" >> "$batch"
    fi
done
cat /etc/openvpn-portal/firewall.nft >> "$batch"
nft --check --file "$batch"
nft --file "$batch"
