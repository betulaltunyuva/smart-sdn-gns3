"""
Smart SDN (GNS3) - Aşama 7: dashboard veri okuyucu (salt okunur)

Veri kaynakları:
  1) runtime/state.json : controller process'inin (utils/runtime_state.py)
     atomik olarak yazdığı canlı durum. Topoloji, metrikler, agent
     durumları, recovery ve olaylar buradan gelir.
  2) /proc               : çalışan osken-manager controller süreçleri.
  3) docker (opsiyonel)  : GNS3 OVS container adları, management interface/IP
     ve OVS tarafındaki controller bağlantısı. Yalnızca OKUMA komutları
     (docker ps, ovs-vsctl get, ip addr) çalıştırılır; hiçbir ayar
     değiştirilmez. Docker yoksa switchler DPID ile gösterilir.

Bu modül Streamlit'e bağımlı değildir.
"""

import concurrent.futures
import json
import os
import re
import subprocess
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.environ.get("SDN_STATE_PATH",
                            os.path.join(PROJECT_ROOT, "runtime", "state.json"))
# state.json bu süreden eskiyse controller çevrimdışı/askıda kabul edilir
STALE_AFTER_SEC = float(os.environ.get("SDN_STATE_STALE_SEC", "6"))
MGMT_PREFIX = os.environ.get("SDN_MGMT_PREFIX", "192.168.122.")
OVS_BRIDGE = os.environ.get("SDN_OVS_BRIDGE", "br0")
# GNS3 container adı: GNS3.<node adı>.<proje uuid>
_GNS3_NAME_RE = re.compile(r"^GNS3\.(?P<node>.+)\.(?P<project>[0-9a-f-]{8,})$")
_INET_RE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/\d+")


# ----------------------------------------------------------------------
# state.json
# ----------------------------------------------------------------------
def load_state(path=STATE_PATH):
    """(state | None, hata | None, dosya_yaşı_sn | None) döner.

    Yazıcı os.replace kullandığından dosya her zaman tam bir JSON'dur; yine
    de okuma sırasında oluşabilecek her hata yakalanır ve çağıran son
    geçerli durumu kullanmaya devam eder."""
    try:
        with open(path, "r") as f:
            raw = f.read()
    except FileNotFoundError:
        return None, "state dosyası yok: %s" % path, None
    except OSError as e:
        return None, "state okunamadı: %s" % e, None
    try:
        state = json.loads(raw)
    except ValueError as e:
        return None, "state JSON geçersiz: %s" % e, None
    if not isinstance(state, dict):
        return None, "state beklenen biçimde değil", None
    ts = state.get("timestamp")
    age = (time.time() - ts) if isinstance(ts, (int, float)) else None
    return state, None, age


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def controller_processes():
    """Çalışan osken-manager ... sdn_controller.py süreçleri:
    [{"pid", "cmdline"}]. Yalnızca /proc okunur (Linux)."""
    procs = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return procs
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % entry, "rb") as f:
                parts = f.read().split(b"\0")
        except OSError:
            continue
        cmd = " ".join(p.decode("utf-8", "replace") for p in parts if p)
        if "osken-manager" in cmd and "sdn_controller.py" in cmd:
            procs.append({"pid": int(entry), "cmdline": cmd})
    return sorted(procs, key=lambda p: p["pid"])


def controller_status(state, age):
    """ONLINE | STALE | OFFLINE ve açıklama."""
    if state is None:
        return "OFFLINE", "state.json yok (controller hiç çalışmadı mı?)"
    pid = (state.get("controller") or {}).get("pid")
    alive = pid_alive(pid)
    if age is not None and age <= STALE_AFTER_SEC and alive:
        return "ONLINE", "PID %s" % pid
    if alive:
        return "STALE", "PID %s yaşıyor ama state %.0f sn eski" % (pid, age or -1)
    return "OFFLINE", "PID %s çalışmıyor (son veri %.0f sn önce)" % (
        pid, age or -1)


# ----------------------------------------------------------------------
# OVS envanteri (docker, salt okunur)
# ----------------------------------------------------------------------
def _run(cmd, timeout=4):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=False)


def _inspect_ovs(container):
    # Tek docker exec ile: DPID, OVS controller bağlantısı, IPv4 adresleri
    script = ("ovs-vsctl get bridge {br} datapath_id 2>/dev/null || echo; "
              "ovs-vsctl get controller {br} is_connected 2>/dev/null || echo; "
              "ip -4 -o addr 2>/dev/null").format(br=OVS_BRIDGE)
    info = {"container": container, "dpid": None, "ovs_connected": None,
            "mgmt_if": None, "mgmt_ip": None, "error": None}
    m = _GNS3_NAME_RE.match(container)
    info["name"] = m.group("node") if m else container
    info["project"] = m.group("project") if m else None
    try:
        out = _run(["docker", "exec", container, "sh", "-c", script])
    except (OSError, subprocess.SubprocessError) as e:
        info["error"] = str(e)
        return info
    lines = out.stdout.splitlines()
    if lines:
        dpid = lines[0].strip().strip('"')
        info["dpid"] = dpid.lower() if re.match(r"^[0-9a-fA-F]{16}$", dpid) \
            else None
    if len(lines) > 1:
        conn = lines[1].strip()
        info["ovs_connected"] = {"true": True, "false": False}.get(conn)
    for line in lines[2:]:
        mm = _INET_RE.match(line.strip())
        if mm and mm.group(2).startswith(MGMT_PREFIX):
            info["mgmt_if"], info["mgmt_ip"] = mm.group(1), mm.group(2)
            break
    if out.returncode != 0 and info["dpid"] is None:
        info["error"] = (out.stderr or "docker exec başarısız").strip()[:200]
    return info


def ovs_inventory():
    """Çalışan OVS container'ları: [{"name", "container", "dpid",
    "mgmt_if", "mgmt_ip", "ovs_connected", "error"}], hata mesajı.

    Switch adı / sayısı sabit değildir: image adı 'openvswitch' içeren veya
    GNS3 adı 'OpenvSwitch' ile başlayan tüm container'lar alınır."""
    try:
        out = _run(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"])
    except (OSError, subprocess.SubprocessError) as e:
        return [], "docker kullanılamıyor: %s" % e
    if out.returncode != 0:
        return [], "docker ps başarısız: %s" % out.stderr.strip()[:200]
    containers = []
    for line in out.stdout.splitlines():
        name, _, image = line.partition("\t")
        m = _GNS3_NAME_RE.match(name)
        node = m.group("node") if m else name
        if "openvswitch" in image.lower() or node.lower().startswith(
                "openvswitch"):
            containers.append(name)
    if not containers:
        return [], None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(_inspect_ovs, containers))
    return sorted(result, key=lambda i: _natural_key(i["name"])), None


def _natural_key(text):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", text or "")]


# ----------------------------------------------------------------------
# Görüntüleme yardımcıları
# ----------------------------------------------------------------------
def short_dpid(dpid_hex):
    if not dpid_hex:
        return "?"
    return "dp-" + (dpid_hex.lstrip("0") or "0")


def name_map(state, inventory):
    """DPID (hex) -> görünen ad. Ad yalnızca docker envanterinden gelir;
    yoksa kısa DPID kullanılır (sabit isim yok)."""
    names = {}
    for item in inventory or ():
        if item.get("dpid"):
            names[item["dpid"]] = item["name"]
    for sw in (state or {}).get("switches") or ():
        if isinstance(sw, dict) and sw.get("dpid") not in names:
            names[sw["dpid"]] = short_dpid(sw.get("dpid"))
    return names


def parse_link_id(link_id):
    """'a:pa<->b:pb' -> ((a, pa), (b, pb)) veya None."""
    try:
        left, right = link_id.split("<->")
        a, pa = left.rsplit(":", 1)
        b, pb = right.rsplit(":", 1)
        return (a, pa), (b, pb)
    except (AttributeError, ValueError):
        return None


def pretty_link(link_id, names):
    parsed = parse_link_id(link_id)
    if parsed is None:
        return link_id or "-"
    (a, pa), (b, pb) = parsed
    return "%s:p%s ⇄ %s:p%s" % (names.get(a, short_dpid(a)), pa,
                                 names.get(b, short_dpid(b)), pb)


def pretty_path(path, names):
    return " → ".join(names.get(d, short_dpid(d)) for d in path or ())


def ago(ts, now=None):
    if not isinstance(ts, (int, float)):
        return "-"
    sec = max(0.0, (now or time.time()) - ts)
    if sec < 1:
        return "şimdi"
    if sec < 60:
        return "%d sn önce" % sec
    if sec < 3600:
        return "%d dk önce" % (sec // 60)
    return "%d sa önce" % (sec // 3600)


def fmt_duration(sec):
    if not isinstance(sec, (int, float)):
        return "-"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dsa %02ddk" % (h, m)
    if m:
        return "%ddk %02dsn" % (m, s)
    return "%dsn" % s
