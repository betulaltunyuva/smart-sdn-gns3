#!/usr/bin/env bash
# Smart SDN (GNS3) - başlangıç scripti (topolojiden bağımsız, dinamik)
#
# Çalışan tüm GNS3.OpenvSwitch-* container'larını keşfeder, her birinde
# management interface'ini otomatik bulur (DHCP + ping 192.168.122.1),
# onu br0 dışında bırakır, br0'ı controller'a bağlar ve OS-Ken controller'ı
# (zaten çalışmıyorsa) başlatır. Tekrar çalıştırılabilir (idempotent).
#
# Kullanım:
#   ./start_sdn.sh                   # OVS'leri ayarla + controller'ı başlat
#   ./start_sdn.sh --no-controller   # yalnızca OVS ayarları
#
# Controller logu: logs/controller.log  (izlemek için: tail -f logs/controller.log)

set -u

# ---------------------------------------------------------------- ayarlar
CONTROLLER_TARGET="tcp:192.168.122.1:6653"
OF_PROTOCOL="OpenFlow13"
BRIDGE="br0"
MGMT_PREFIX="192.168.122."      # kabul edilen management ağı (/24)
MGMT_GATEWAY="192.168.122.1"    # ping ile doğrulanacak adres
DHCP_TRIES="${DHCP_TRIES:-2}"       # aday başına udhcpc deneme sayısı
DHCP_TIMEOUT="${DHCP_TIMEOUT:-2}"   # denemeler arası saniye
CONNECT_WAIT="${CONNECT_WAIT:-20}"  # controller bağlantısı için en fazla bekleme (sn)
OVS_NAME_RE='^GNS3\.OpenvSwitch-[^.]+\.'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER_APP="controller/sdn_controller.py"
CONTROLLER_LOG="$PROJECT_ROOT/logs/controller.log"
CONTROLLER_PATTERN="osken-manager.*sdn_controller\.py"
# Önceki çalıştırmalarda bulunan management portları (yalnızca ipucu; her
# seferinde DHCP+ping ile yeniden doğrulanır). logs/ .gitignore'dadır.
HINT_FILE="$PROJECT_ROOT/logs/mgmt_ports.cache"
LOCK_FILE="$PROJECT_ROOT/logs/.start_sdn.lock"

START_CONTROLLER=1
for arg in "$@"; do
    case "$arg" in
        --no-controller) START_CONTROLLER=0 ;;
        -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "Bilinmeyen argüman: $arg" >&2; exit 2 ;;
    esac
done

# ---------------------------------------------------------------- yardımcılar
if [ -t 1 ]; then
    C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_WARN=$'\e[33m'; C_HDR=$'\e[1;36m'; C_END=$'\e[0m'
else
    C_OK=""; C_ERR=""; C_WARN=""; C_HDR=""; C_END=""
fi
info() { echo "    $*"; }
ok()   { echo "    ${C_OK}[OK]${C_END} $*"; }
warn() { echo "    ${C_WARN}[UYARI]${C_END} $*"; }
err()  { echo "    ${C_ERR}[HATA]${C_END} $*" >&2; }
hdr()  { echo; echo "${C_HDR}== $* ==${C_END}"; }
die()  { echo "${C_ERR}[HATA]${C_END} $*" >&2; exit 1; }

# Container içinde komut çalıştır
dx() { local c="$1"; shift; docker exec "$c" sh -c "$*"; }

# Interface'in 192.168.122.x IPv4 adresi (yoksa boş)
mgmt_ip() {
    dx "$1" "ip -4 addr show dev $2 2>/dev/null" \
        | awk -v p="$MGMT_PREFIX" '$1=="inet" && index($2,p)==1 {split($2,a,"/"); print a[1]; exit}'
}

# Interface hangi bridge'de? (hiçbirinde değilse boş)
port_bridge() { dx "$1" "ovs-vsctl port-to-br $2 2>/dev/null" | tr -d '\r'; }

gateway_reachable() {
    dx "$1" "ping -c 2 -W 2 -I $2 $MGMT_GATEWAY >/dev/null 2>&1"
}

hint_get() { [ -f "$HINT_FILE" ] && awk -v n="$1" '$1==n {print $2; exit}' "$HINT_FILE"; }
hint_set() {
    local tmp="$HINT_FILE.tmp"
    { [ -f "$HINT_FILE" ] && awk -v n="$1" '$1!=n' "$HINT_FILE"; echo "$1 $2"; } > "$tmp" \
        && mv -f "$tmp" "$HINT_FILE"
}

# ---------------------------------------------------------------- ön kontroller
command -v docker >/dev/null 2>&1 || die "docker bulunamadı."
docker ps >/dev/null 2>&1 || die "docker'a erişilemiyor (daemon çalışıyor mu / yetki var mı?)."

mkdir -p "$PROJECT_ROOT/logs"
# Aynı anda iki kopya çalışırsa portları birbirinin altından ayırabilir.
exec 9>"$LOCK_FILE"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
    die "start_sdn.sh zaten çalışıyor."
fi

# ---------------------------------------------------------------- aday testi
# Test edilen adayın orijinal durumu; Ctrl-C gelirse trap ile geri yüklenir.
PROBE_C=""; PROBE_IF=""; PROBE_BR=""; PROBE_OFPORT=""; PROBE_WAS_UP=""

restore_probe() {
    [ -z "$PROBE_IF" ] && return 0
    local c="$PROBE_C" ifc="$PROBE_IF"
    dx "$c" "ip -4 addr flush dev $ifc; [ -f /tmp/.start_sdn.resolv ] && mv -f /tmp/.start_sdn.resolv /etc/resolv.conf; true"
    if [ -n "$PROBE_BR" ]; then
        local req=""
        [[ "$PROBE_OFPORT" =~ ^[0-9]+$ ]] && [ "$PROBE_OFPORT" -gt 0 ] \
            && req="-- set Interface $ifc ofport_request=$PROBE_OFPORT"
        if dx "$c" "ovs-vsctl --may-exist add-port $PROBE_BR $ifc $req"; then
            info "$ifc geri eklendi -> $PROBE_BR${req:+ (ofport $PROBE_OFPORT)}"
        else
            err "$ifc, $PROBE_BR bridge'ine GERİ EKLENEMEDİ! Elle: ovs-vsctl add-port $PROBE_BR $ifc"
        fi
    fi
    [ "$PROBE_WAS_UP" = "0" ] && dx "$c" "ip link set dev $ifc down"
    PROBE_IF=""
}

on_interrupt() {
    echo
    err "Kesildi; test edilen aday eski haline getiriliyor..."
    restore_probe
    exit 130
}
trap on_interrupt INT TERM

# Adayı test et: bridge'den ayır, UP yap, DHCP dene, IP + ping doğrula.
# Başarılıysa 0 döner ve port br0 dışında kalır; değilse eski haline döner.
probe_candidate() {
    local c="$1" ifc="$2"
    PROBE_C="$c"; PROBE_IF="$ifc"
    PROBE_BR=$(port_bridge "$c" "$ifc")
    PROBE_OFPORT=""
    [ -n "$PROBE_BR" ] && PROBE_OFPORT=$(dx "$c" "ovs-vsctl get Interface $ifc ofport" | tr -d '\r')
    PROBE_WAS_UP=0
    dx "$c" "ip link show dev $ifc" | grep -q '[<,]UP[,>]' && PROBE_WAS_UP=1

    info "Aday $ifc test ediliyor (bridge: ${PROBE_BR:-yok}${PROBE_OFPORT:+, ofport $PROBE_OFPORT})..."
    dx "$c" "cp -f /etc/resolv.conf /tmp/.start_sdn.resolv 2>/dev/null; true"
    if [ -n "$PROBE_BR" ] && ! dx "$c" "ovs-vsctl --if-exists del-port $PROBE_BR $ifc"; then
        err "$ifc, $PROBE_BR'dan ayrılamadı; atlanıyor."
        PROBE_IF=""; return 1
    fi
    dx "$c" "ip link set dev $ifc up"
    dx "$c" "udhcpc -i $ifc -n -q -t $DHCP_TRIES -T $DHCP_TIMEOUT >/dev/null 2>&1"

    local ip; ip=$(mgmt_ip "$c" "$ifc")
    if [ -n "$ip" ] && gateway_reachable "$c" "$ifc"; then
        dx "$c" "rm -f /tmp/.start_sdn.resolv"
        PROBE_IF=""
        FOUND_IP="$ip"
        return 0
    fi
    if [ -n "$ip" ]; then
        info "$ifc IP aldı ($ip) ama $MGMT_GATEWAY'e ping yok; reddedildi."
    else
        info "$ifc: ${MGMT_PREFIX}0/24 ağından IP alınamadı."
    fi
    restore_probe
    return 1
}

# ---------------------------------------------------------------- OVS ayarı
declare -A NAME_OF MGMT_IF MGMT_IP STATUS
CONTAINERS=()

configure_ovs() {
    local c="$1" name="${NAME_OF[$1]}"
    hdr "$name"
    info "Container: $c"

    if ! dx "$c" "ovs-vsctl br-exists $BRIDGE"; then
        err "$BRIDGE bridge'i yok (ovs-vswitchd hazır olmayabilir)."
        STATUS[$c]="$BRIDGE yok"; return 1
    fi

    # eth* interface'lerini güvenli biçimde listele (yalnızca ^eth[0-9]+$)
    local all_ifs
    all_ifs=$(dx "$c" "ls /sys/class/net" | tr -d '\r' | grep -E '^eth[0-9]+$' | sort -V)
    if [ -z "$all_ifs" ]; then
        err "Container içinde eth* interface'i yok."
        STATUS[$c]="eth* yok"; return 1
    fi

    # 1) Hızlı yol: br dışında, zaten 192.168.122.x IP'li ve gateway'e
    #    ping atabilen port varsa yeniden tarama yapma.
    local ifc ip found=""
    for ifc in $all_ifs; do
        [ -n "$(port_bridge "$c" "$ifc")" ] && continue
        ip=$(mgmt_ip "$c" "$ifc")
        [ -z "$ip" ] && continue
        if gateway_reachable "$c" "$ifc"; then
            ok "Management port mevcut: $ifc ($ip) - tarama atlandı."
            found="$ifc"; FOUND_IP="$ip"; break
        else
            warn "$ifc IP'li ($ip) ama $MGMT_GATEWAY'e ping yok; taramaya dahil edilecek."
        fi
    done

    # 2) Tarama: önce önceki çalıştırmadaki ipucu, sonra bridge dışındaki
    #    portlar (veri düzlemine dokunmaz), en son br'deki portlar.
    if [ -z "$found" ]; then
        local hint free=() bridged=() candidates=()
        hint=$(hint_get "$name")
        for ifc in $all_ifs; do
            [ "$ifc" = "$hint" ] && continue
            if [ -n "$(port_bridge "$c" "$ifc")" ]; then bridged+=("$ifc"); else free+=("$ifc"); fi
        done
        if [ -n "$hint" ] && grep -qx "$hint" <<<"$all_ifs"; then
            candidates+=("$hint")
        fi
        candidates+=("${free[@]}" "${bridged[@]}")

        info "Management port aranıyor (${#candidates[@]} aday${hint:+, ipucu: $hint})..."
        for ifc in "${candidates[@]}"; do
            if probe_candidate "$c" "$ifc"; then
                found="$ifc"
                ok "Management port bulundu: $ifc ($FOUND_IP)"
                break
            fi
        done
    fi

    if [ -z "$found" ]; then
        err "$name için management port BULUNAMADI (hiçbir eth* ${MGMT_PREFIX}0/24'ten IP alıp $MGMT_GATEWAY'e ping atamadı)."
        err "GNS3'te bir portun NAT/virbr0 bulutuna bağlı olduğunu kontrol edin. Diğer switch'lere devam ediliyor."
        STATUS[$c]="mgmt port yok"
        # br0 ayarlarını yine de doğrula; IP olmadan zararsız.
    else
        MGMT_IF[$c]="$found"; MGMT_IP[$c]="$FOUND_IP"
        hint_set "$name" "$found"
        # Management port br0 (ve diğer bridge'ler) dışında kalmalı.
        local owner; owner=$(port_bridge "$c" "$found")
        if [ -n "$owner" ]; then
            dx "$c" "ovs-vsctl --if-exists del-port $owner $found" \
                && ok "$found, $owner'dan ayrıldı." || err "$found, $owner'dan ayrılamadı."
        fi
    fi

    # 3) br0: controller / OpenFlow13 / fail-mode=secure (aynıysa dokunma)
    local cur
    cur=$(dx "$c" "ovs-vsctl get-controller $BRIDGE" | tr -d '\r' | xargs)
    if [ "$cur" = "$CONTROLLER_TARGET" ]; then
        ok "Controller zaten $CONTROLLER_TARGET"
    elif dx "$c" "ovs-vsctl set-controller $BRIDGE $CONTROLLER_TARGET"; then
        ok "Controller ayarlandı: $CONTROLLER_TARGET (önceki: ${cur:-yok})"
    else
        err "Controller ayarlanamadı."
    fi

    cur=$(dx "$c" "ovs-vsctl get bridge $BRIDGE protocols" | tr -d '\r')
    if [ "$cur" = "[$OF_PROTOCOL]" ]; then
        ok "protocols zaten $cur"
    elif dx "$c" "ovs-vsctl set bridge $BRIDGE protocols=$OF_PROTOCOL"; then
        ok "protocols=$OF_PROTOCOL uygulandı (önceki: $cur)"
    else
        err "protocols ayarlanamadı."
    fi

    cur=$(dx "$c" "ovs-vsctl get-fail-mode $BRIDGE" | tr -d '\r')
    if [ "$cur" = "secure" ]; then
        ok "fail-mode zaten secure"
    elif dx "$c" "ovs-vsctl set-fail-mode $BRIDGE secure"; then
        ok "fail-mode=secure uygulandı (önceki: ${cur:-yok})"
    else
        err "fail-mode ayarlanamadı."
    fi

    STATUS[$c]="${STATUS[$c]:-hazır}"
    return 0
}

# ---------------------------------------------------------------- keşif
hdr "Keşif"
mapfile -t found_containers < <(docker ps --format '{{.Names}}' | grep -E "$OVS_NAME_RE" || true)
if [ "${#found_containers[@]}" -eq 0 ]; then
    die "Çalışan GNS3.OpenvSwitch-* container'ı bulunamadı (GNS3 projesi açık ve node'lar başlatılmış mı?)."
fi
# GNS3.<isim>.<proje-uuid> -> <isim>; isme göre doğal sırala (2 < 10)
while IFS=$'\t' read -r name c; do
    CONTAINERS+=("$c"); NAME_OF[$c]="$name"
done < <(for c in "${found_containers[@]}"; do
            n="${c#GNS3.}"; printf '%s\t%s\n' "${n%.*}" "$c"
         done | sort -V)

dups=$(for c in "${CONTAINERS[@]}"; do echo "${NAME_OF[$c]}"; done | sort | uniq -d)
if [ -n "$dups" ]; then
    warn "Aynı isimli birden fazla OVS var (birden çok GNS3 projesi açık olabilir): $(echo $dups)"
    for c in "${CONTAINERS[@]}"; do
        grep -qx "${NAME_OF[$c]}" <<<"$dups" && NAME_OF[$c]="${NAME_OF[$c]}@${c##*.}"
    done
fi
info "${#CONTAINERS[@]} OVS bulundu: $(for c in "${CONTAINERS[@]}"; do printf '%s ' "${NAME_OF[$c]}"; done)"

for c in "${CONTAINERS[@]}"; do
    FOUND_IP=""
    configure_ovs "$c" || true
done

# ---------------------------------------------------------------- controller
start_controller() {
    hdr "Controller"
    local pids
    pids=$(pgrep -f "$CONTROLLER_PATTERN" || true)
    if [ -n "$pids" ]; then
        if [ "$(wc -l <<<"$pids")" -gt 1 ]; then
            warn "BİRDEN FAZLA controller süreci çalışıyor; hiçbiri otomatik kapatılmadı:"
            ps -o pid=,etime=,cmd= -p "$(paste -sd, <<<"$pids")" | sed 's/^/        /'
            warn "Switch'ler farklı süreçlere bölünebilir. Fazlalığı elle kapatın: kill <PID>"
        else
            ok "Controller zaten çalışıyor (PID: $pids); ikinci kez başlatılmadı."
        fi
        return 0
    fi
    command -v osken-manager >/dev/null 2>&1 || { err "osken-manager bulunamadı."; return 1; }
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE '[:.]6653$'; then
        err "6653 portu başka bir süreç tarafından kullanılıyor; controller başlatılmadı."
        return 1
    fi

    echo "----- $(date '+%F %T') start_sdn.sh -----" >> "$CONTROLLER_LOG"
    (cd "$PROJECT_ROOT" && nohup osken-manager --observe-links "$CONTROLLER_APP" \
        >> "$CONTROLLER_LOG" 2>&1 9>&- &)
    sleep 2
    pids=$(pgrep -f "$CONTROLLER_PATTERN" || true)
    if [ -n "$pids" ]; then
        ok "Controller başlatıldı (PID: $(echo $pids)). Log: $CONTROLLER_LOG"
    else
        err "Controller başlatılamadı. Son log satırları:"
        tail -n 20 "$CONTROLLER_LOG" >&2
        return 1
    fi
}

if [ "$START_CONTROLLER" -eq 1 ]; then
    start_controller || true
else
    hdr "Controller"
    info "--no-controller verildi; controller başlatılmadı."
fi

# ---------------------------------------------------------------- durum özeti
# Controller kaydına bridge adıyla erişilir (br0'da tek controller var)
conn_state() {
    dx "$1" "ovs-vsctl get controller $BRIDGE is_connected" 2>/dev/null | tr -d '\r' | head -n1
}

if pgrep -f "$CONTROLLER_PATTERN" >/dev/null 2>&1; then
    for ((i = 0; i < CONNECT_WAIT; i++)); do
        all=1
        for c in "${CONTAINERS[@]}"; do
            [ "$(conn_state "$c")" = "true" ] || { all=0; break; }
        done
        [ "$all" -eq 1 ] && break
        sleep 1
    done
fi

hdr "Özet"
printf '    %-15s %-6s %-17s %-11s %s\n' "OVS" "PORT" "MGMT IP" "CONTROLLER" "DURUM"
printf '    %-15s %-6s %-17s %-11s %s\n' "---" "----" "-------" "----------" "-----"
for c in "${CONTAINERS[@]}"; do
    case "$(conn_state "$c")" in
        true)  conn="${C_OK}BAĞLI${C_END}      " ;;
        false) conn="${C_ERR}BAĞLI DEĞİL${C_END}" ;;
        *)     conn="${C_WARN}bilinmiyor${C_END} " ;;
    esac
    printf '    %-15s %-6s %-17s %s %s\n' "${NAME_OF[$c]}" "${MGMT_IF[$c]:--}" \
        "${MGMT_IP[$c]:--}" "$conn" "${STATUS[$c]:-?}"
done
echo
[ "$START_CONTROLLER" -eq 1 ] && echo "Controller logunu izlemek için: tail -f logs/controller.log"
exit 0
