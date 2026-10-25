#!/bin/sh

PKG_DIR=/etc/network/pkgs
NFT_FILE=/etc/network/nat.nft

# IPv4 forwarding açık olsun
sysctl -w net.ipv4.ip_forward=1 >/dev/null

# eth1 DHCP adresini alana kadar bekle
i=0
while ! ip addr show eth1 2>/dev/null | grep -q 'inet '; do
    i=$((i+1))
    [ "$i" -ge 30 ] && exit 0
    sleep 1
done

# nftables container yeniden açıldığında kaybolmuşsa
# sakladığımız paketlerden tekrar kur
if ! command -v nft >/dev/null 2>&1; then
    apk add --no-network --allow-untrusted "$PKG_DIR"/*.apk >/dev/null 2>&1
fi

# nft hâlâ yoksa çık
command -v nft >/dev/null 2>&1 || exit 0

# NAT tablosunu temiz şekilde yeniden yükle
nft delete table ip sdn_nat 2>/dev/null || true
nft -f "$NFT_FILE"

exit 0
