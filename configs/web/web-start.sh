#!/bin/sh

PKG_DIR=/etc/network/web-pkgs
CONF=/etc/network/lighttpd-sdn.conf

# lighttpd yoksa kalici paketlerden tekrar kur
if ! command -v lighttpd >/dev/null 2>&1; then
    apk add --no-network --allow-untrusted "$PKG_DIR"/*.apk >/dev/null 2>&1
fi

command -v lighttpd >/dev/null 2>&1 || exit 0

# Eski lighttpd varsa kapat
killall lighttpd 2>/dev/null || true

# Config kontrolü ve baslatma
lighttpd -tt -f "$CONF" >/dev/null 2>&1 || exit 0
lighttpd -f "$CONF"

exit 0
