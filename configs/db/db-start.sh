#!/bin/sh

PKG_DIR=/etc/network/db-pkgs
CONF=/etc/network/mariadb-sdn.cnf

# MariaDB yoksa kalici paketlerden yeniden kur
if ! command -v mariadbd >/dev/null 2>&1; then
    apk add --no-network --allow-untrusted "$PKG_DIR"/*.apk >/dev/null 2>&1
fi

command -v mariadbd >/dev/null 2>&1 || exit 1

mkdir -p /run/mysqld
chown mysql:mysql /run/mysqld
chown -R mysql:mysql /etc/network/db-data

# Zaten calisiyorsa tekrar baslatma
if pidof mariadbd >/dev/null 2>&1; then
    exit 0
fi

mariadbd --defaults-file="$CONF" --user=mysql >/tmp/mariadb.log 2>&1 &

exit 0
