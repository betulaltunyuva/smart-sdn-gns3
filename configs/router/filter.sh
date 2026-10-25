#!/bin/sh

FILTER_FILE=/etc/network/filter.nft

command -v nft >/dev/null 2>&1 || exit 0

nft delete table ip sdn_filter 2>/dev/null || true
nft -f "$FILTER_FILE"

exit 0
