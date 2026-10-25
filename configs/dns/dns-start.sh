#!/bin/sh

PKG_DIR=/etc/network/dns-pkgs
CONF=/etc/network/dnsmasq-sdn.conf

# dnsmasq yoksa kalici paketlerden kur
if ! command -v dnsmasq >/dev/null 2>&1; then
    apk add --no-network --allow-untrusted "$PKG_DIR"/*.apk >/dev/null 2>&1
fi

command -v dnsmasq >/dev/null 2>&1 || exit 0

# eth0 IP adresi gelene kadar bekle
i=0
while ! ip -4 addr show eth0 2>/dev/null | grep -q '10.10.50.53'; do
    i=$((i+1))
    [ "$i" -ge 30 ] && exit 0
    sleep 1
done

# Eski dnsmasq varsa kapat ve bizim config ile baslat
killall dnsmasq 2>/dev/null || true

dnsmasq --test --conf-file="$CONF" >/dev/null 2>&1 || exit 0
dnsmasq --conf-file="$CONF"

exit 0
