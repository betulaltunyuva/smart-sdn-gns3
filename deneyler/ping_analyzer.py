"""
Aşama 8.5 - PC1 (10.0.0.1) -> PC2 (10.0.0.2) ping deneyleri için analiz modülü.

Yalnızca Python standart kütüphanesi kullanılır. Çalışan ağa hiçbir şey
göndermez; yalnızca kaydedilmiş dosyaları OKUR:

  * VPCS ping çıktısının yapıştırıldığı metin dosyası (birincil kaynak)
  * İsteğe bağlı pcap (PC1 <-> ubridge UDP tüneli veya GNS3 link capture)
  * İsteğe bağlı runtime/state.json KOPYASI (Controller olay zaman damgaları)

Ölçüm tanımları (rapor ve CSV'de bu tanımlar geçerlidir):
  gozlenen_paket   Sonucu (yanıt / timeout / ICMP hata) kayıtta bulunan seq sayısı
  kayip_paket      Açıkça "timeout" veya ICMP hata ile biten seq sayısı
  eksik_seq        1..beklenen aralığında kayıtta HİÇ görünmeyen seq'ler.
                   Kayıp sayılmaz; ölçüm BELIRSIZ işaretlenir ve kayıp oranı
                   alt/üst sınır olarak verilir.
  kayip_yuzde      kayip_paket / gozlenen_paket * 100
  P95              En yakın sıra (nearest-rank) yöntemi: sıralı RTT'lerde
                   ceil(0.95 * n). eleman
  jitter           Ardışık seq numaralı (i, i+1) İKİ paket de yanıtlandığında
                   |RTT(i+1) - RTT(i)| değerlerinin ortalaması (RFC 3393 IPDV
                   mutlak değer ortalaması; RFC 3550 üstel yumuşatması YOK).
                   Kayıp boşluğunu aşan çiftler kullanılmaz.
  kesinti_nominal  En uzun kayıp patlaması (paket) x ping aralığı. Metin
                   kaydında zaman damgası olmadığından TAHMİNDİR (+/- 1 aralık).
  kesinti_olculen  Yalnız zaman damgalı kaynakta (pcap): kesintiden önceki son
                   yanıt ile sonraki ilk yanıt arasındaki süre.
  Controller tepki süreleri state.json olaylarından ayrıca hesaplanır ve
  uçtan uca kesinti ile KARIŞTIRILMAZ.
"""

import argparse
import json
import math
import re
import statistics
import struct
import sys
from dataclasses import dataclass, field

DEFAULT_SRC = "10.0.0.1"
DEFAULT_DST = "10.0.0.2"
DEFAULT_INTERVAL_MS = 1000          # VPCS varsayılan ping aralığı

SCENARIOS = {
    "normal": "Normal ağ iletişimi",
    "baglanti_kopmasi": "Bağlantı kopması (ping sırasında Suspend)",
    "otomatik_kurtarma": "Otomatik kurtarma (link kopukken alternatif yol)",
    "failback": "Failback (ping sırasında Resume)",
}
# Kesinti beklenmeyen, kararlı durum senaryoları: herhangi bir kayıp = başarısız
STEADY_SCENARIOS = ("normal", "otomatik_kurtarma")

REPLY = "yanit"
TIMEOUT = "timeout"
ICMP_ERROR = "icmp_hata"

_TS = r"(?:\[(?P<ts>\d+(?:\.\d+)?)\]\s*)?"
REPLY_RE = re.compile(_TS + r"\d+\s+bytes from\s+(?P<ip>[\d.]+):?\s+"
                      r"icmp_seq=(?P<seq>\d+)\s+ttl=\d+\s+"
                      r"time=(?P<rtt>\d+(?:\.\d+)?)\s*ms(?P<dup>.*DUP!)?")
TIMEOUT_RE = re.compile(_TS + r"(?:(?P<ip>[\d.]+)\s+icmp_seq=(?P<seq>\d+)\s+"
                        r"timeout|no answer yet for icmp_seq=(?P<seq2>\d+))")
ICMP_ERR_RE = re.compile(r"^\*(?P<ip>[\d.]+)\s+icmp_seq=(?P<seq>\d+).*"
                         r"\((?P<msg>ICMP type:\d+, code:\d+[^)]*)\)")
NOT_REACHABLE_RE = re.compile(r"host \((?P<ip>[\d.]+)\) not reachable")
PING_CMD_RE = re.compile(r"\bping\s+(?P<ip>\d+\.\d+\.\d+\.\d+)(?P<args>.*)$")
HEADER_RE = re.compile(r"^#\s*(?P<key>[a-z_]+)\s*:\s*(?P<val>.*?)\s*$")
SEQ_HINT_RE = re.compile(r"icmp_seq")


class MeasurementError(Exception):
    """Kaynaktan güvenilir ölçüm çıkarılamadığında atılır."""


@dataclass
class PingRecord:
    seq: int
    status: str                     # REPLY / TIMEOUT / ICMP_ERROR
    rtt_ms: float = None
    t_sent: float = None            # epoch (yalnız zaman damgalı kaynak)
    t_reply: float = None


@dataclass
class ParsedLog:
    records: list = field(default_factory=list)   # seq sırasına göre
    meta: dict = field(default_factory=dict)
    expected: int = None
    interval_ms: float = DEFAULT_INTERVAL_MS
    source: str = "vpcs_metin"
    warnings: list = field(default_factory=list)


# ----------------------------------------------------------------------
# VPCS metin kaydı
# ----------------------------------------------------------------------
def parse_ping_text(text, target=DEFAULT_DST):
    """VPCS (ve Linux ping) çıktısını ayrıştırır.

    Aynı seq iki kez görülürse (iki ping oturumu aynı dosyada, DUP vb.)
    ilk kayıt tutulur ve uyarı eklenir.
    """
    log = ParsedLog()
    by_seq = {}
    unparsed = 0
    other_target = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        h = HEADER_RE.match(line)
        if h:
            log.meta[h.group("key")] = h.group("val")
            continue
        if line.startswith("#"):
            continue
        cmd = PING_CMD_RE.search(line)
        if cmd and "icmp_seq" not in line:
            _apply_ping_args(log, cmd.group("args"))
            if cmd.group("ip") != target:
                log.warnings.append("ping komutu farklı hedefe: %s"
                                    % cmd.group("ip"))
            continue
        rec, ip = _parse_line(line)
        if rec is None:
            if NOT_REACHABLE_RE.search(line):
                log.meta["not_reachable"] = "1"
                log.warnings.append("VPCS 'not reachable' bildirdi (ARP "
                                    "çözülemedi, ping gönderilmedi)")
            elif SEQ_HINT_RE.search(line):
                unparsed += 1
            continue
        if ip is not None and ip != target:
            other_target += 1
            continue
        if rec.seq in by_seq:
            log.warnings.append("seq %d birden fazla kez görüldü (ilk kayıt "
                                "kullanıldı)" % rec.seq)
            continue
        by_seq[rec.seq] = rec
    if unparsed:
        log.warnings.append("%d satır icmp_seq içeriyor ama tanınmadı"
                            % unparsed)
    if other_target:
        log.warnings.append("%d satır farklı hedef IP'ye ait, yok sayıldı"
                            % other_target)
    log.records = [by_seq[s] for s in sorted(by_seq)]
    _apply_header(log)
    return log


def _parse_line(line):
    m = REPLY_RE.search(line)
    if m:
        if m.group("dup"):
            return None, None
        ts = float(m.group("ts")) if m.group("ts") else None
        return PingRecord(int(m.group("seq")), REPLY, float(m.group("rtt")),
                          t_reply=ts), m.group("ip")
    m = ICMP_ERR_RE.search(line)
    if m:
        return PingRecord(int(m.group("seq")), ICMP_ERROR), m.group("ip")
    m = TIMEOUT_RE.search(line)
    if m:
        seq = m.group("seq") or m.group("seq2")
        return PingRecord(int(seq), TIMEOUT), m.group("ip")
    return None, None


def _apply_ping_args(log, args):
    c = re.search(r"-c\s+(\d+)", args)
    i = re.search(r"-i\s+(\d+(?:\.\d+)?)", args)   # VPCS: milisaniye
    if c:
        log.expected = int(c.group(1))
    if i:
        log.interval_ms = float(i.group(1))


def _apply_header(log):
    m = log.meta
    if m.get("paket_sayisi", "").isdigit():
        n = int(m["paket_sayisi"])
        # Gerçekte çalışan komuttaki -c değeri esastır; başlık yedektir
        if log.expected is None:
            log.expected = n
        elif log.expected != n:
            log.warnings.append("başlıktaki paket_sayisi (%d) ile ping -c "
                                "(%d) farklı; -c kullanıldı"
                                % (n, log.expected))
    try:
        if m.get("aralik_ms"):
            log.interval_ms = float(m["aralik_ms"])
    except ValueError:
        log.warnings.append("aralik_ms okunamadı: %r" % m["aralik_ms"])


# ----------------------------------------------------------------------
# pcap (tcpdump / GNS3 capture)
# ----------------------------------------------------------------------
_LINKTYPE_ETHERNET, _LINKTYPE_NULL = 1, 0
_LINKTYPE_SLL, _LINKTYPE_SLL2 = 113, 276


def read_pcap_icmp(path, src=DEFAULT_SRC, dst=DEFAULT_DST):
    """Klasik pcap dosyasından src->dst ICMP echo request/reply çiftlerini çıkarır.

    GNS3 UDP tüneli (ubridge) yakalandıysa UDP yükü içindeki Ethernet çerçevesi
    bir seviye açılır. Hiç echo request bulunmazsa MeasurementError atılır:
    yakalamanın ICMP gördüğü doğrulanmadan ölçüm üretilmez.
    """
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 24:
        raise MeasurementError("pcap dosyası boş veya bozuk: %s" % path)
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    elif magic == b"\x0a\x0d\x0d\x0a":
        raise MeasurementError("pcapng desteklenmiyor; tcpdump -w ile klasik "
                               "pcap kaydedin")
    else:
        raise MeasurementError("pcap biçimi tanınmadı: %s" % path)
    nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    linktype = struct.unpack(endian + "I", data[20:24])[0]

    requests, replies = {}, {}
    ids = set()
    frames = 0
    off = 24
    while off + 16 <= len(data):
        sec, frac, incl, _ = struct.unpack(endian + "IIII", data[off:off + 16])
        pkt = data[off + 16:off + 16 + incl]
        off += 16 + incl
        frames += 1
        t = sec + frac / (1e9 if nano else 1e6)
        icmp = _icmp_from_link(pkt, linktype)
        if icmp is None:
            continue
        ip_src, ip_dst, itype, ident, seq = icmp
        if itype == 8 and ip_src == src and ip_dst == dst:
            requests.setdefault((ident, seq), t)
            ids.add(ident)
        elif itype == 0 and ip_src == dst and ip_dst == src:
            replies.setdefault((ident, seq), t)

    log = ParsedLog(source="pcap")
    if not requests:
        raise MeasurementError(
            "pcap içinde %s -> %s ICMP echo request bulunamadı (%d çerçeve). "
            "Yakalama doğru arayüzü/portu görmüyor olabilir; ölçüm yapılmadı."
            % (src, dst, frames))
    if len(ids) > 1:
        log.warnings.append("pcap'te %d farklı ICMP kimliği var (birden fazla "
                            "ping oturumu olabilir)" % len(ids))
    last_t = max(list(requests.values()) + list(replies.values()))
    # İstekler gönderim zamanına göre 1..N numaralanır: ICMP seq alanının
    # bayt sırası uygulamaya göre değişebildiğinden sıra numarası kullanılır.
    ordered = sorted(requests.items(), key=lambda kv: kv[1])
    for n, (key, t_req) in enumerate(ordered, 1):
        t_rep = replies.get(key)
        if t_rep is not None and t_rep >= t_req:
            log.records.append(PingRecord(n, REPLY,
                                          round((t_rep - t_req) * 1000, 3),
                                          t_req, t_rep))
        else:
            log.records.append(PingRecord(n, TIMEOUT, t_sent=t_req))
    if log.records[-1].status == TIMEOUT and last_t - log.records[-1].t_sent < 1:
        log.warnings.append("son istek yakalama bitmeden 1 sn içinde "
                            "gönderilmiş; yanıtı kaçmış olabilir")
    log.meta["pcap_cerceve"] = str(frames)
    log.meta["pcap_istek"] = str(len(requests))
    log.meta["pcap_yanit"] = str(len(replies))
    return log


def _icmp_from_link(pkt, linktype):
    if linktype == _LINKTYPE_ETHERNET:
        return _icmp_from_eth(pkt, 0)
    if linktype == _LINKTYPE_SLL and len(pkt) >= 16:
        return _icmp_from_l3(struct.unpack("!H", pkt[14:16])[0], pkt[16:], 0)
    if linktype == _LINKTYPE_SLL2 and len(pkt) >= 20:
        return _icmp_from_l3(struct.unpack("!H", pkt[0:2])[0], pkt[20:], 0)
    if linktype == _LINKTYPE_NULL and len(pkt) >= 4:
        return _icmp_from_l3(0x0800, pkt[4:], 0)
    return None


def _icmp_from_eth(frame, depth):
    if len(frame) < 14:
        return None
    etype = struct.unpack("!H", frame[12:14])[0]
    payload = frame[14:]
    while etype in (0x8100, 0x88A8) and len(payload) >= 4:   # VLAN etiketi
        etype = struct.unpack("!H", payload[2:4])[0]
        payload = payload[4:]
    return _icmp_from_l3(etype, payload, depth)


def _icmp_from_l3(etype, ip, depth):
    if etype != 0x0800 or len(ip) < 20 or ip[0] >> 4 != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    proto = ip[9]
    src = ".".join(str(b) for b in ip[12:16])
    dst = ".".join(str(b) for b in ip[16:20])
    body = ip[ihl:]
    if proto == 1 and len(body) >= 8:
        itype = body[0]
        ident, seq = struct.unpack("!HH", body[4:8])
        return src, dst, itype, ident, seq
    if proto == 17 and depth == 0 and len(body) > 8:
        # GNS3 UDP NIO: UDP yükü ham Ethernet çerçevesidir
        return _icmp_from_eth(body[8:], 1)
    return None


# ----------------------------------------------------------------------
# İstatistikler
# ----------------------------------------------------------------------
def percentile_nearest_rank(values, p):
    if not values:
        return None
    ordered = sorted(values)
    k = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[k - 1]


def jitter_ms(records):
    """Ardışık seq çiftlerinde |ΔRTT| ortalaması (bkz. modül açıklaması)."""
    rtt = {r.seq: r.rtt_ms for r in records if r.status == REPLY}
    diffs = [abs(rtt[s + 1] - rtt[s]) for s in rtt if s + 1 in rtt]
    return statistics.mean(diffs) if diffs else None


def rtt_stats(records):
    vals = [r.rtt_ms for r in records if r.status == REPLY]
    if not vals:
        return {"n": 0, "min": None, "max": None, "ort": None,
                "medyan": None, "p95": None, "std": None, "jitter": None}
    return {"n": len(vals), "min": min(vals), "max": max(vals),
            "ort": statistics.mean(vals), "medyan": statistics.median(vals),
            "p95": percentile_nearest_rank(vals, 95),
            "std": statistics.stdev(vals) if len(vals) > 1 else 0.0,
            "jitter": jitter_ms(records)}


def loss_bursts(records):
    """Ardışık seq'lerde açıkça kaybolan paket dizileri: [(ilk, son, uzunluk)].

    Kayıtta görünmeyen (eksik) seq bir patlamayı böler; eksik paket kayıp
    sayılmaz.
    """
    bursts, start, prev = [], None, None
    for r in records:
        lost = r.status != REPLY
        contiguous = prev is not None and r.seq == prev + 1
        if lost and start is not None and contiguous:
            prev = r.seq
            continue
        if start is not None:
            bursts.append((start, prev, prev - start + 1))
            start = None
        if lost:
            start = r.seq
        prev = r.seq
    if start is not None:
        bursts.append((start, prev, prev - start + 1))
    return bursts


def _ranges(nums):
    out, nums = [], sorted(nums)
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else "%d-%d" % (nums[i], nums[j]))
        i = j + 1
    return ",".join(out)


# ----------------------------------------------------------------------
# Controller olayları (state.json kopyası)
# ----------------------------------------------------------------------
def load_incidents(state_path):
    with open(state_path, encoding="utf-8") as f:
        return json.load(f).get("incidents", [])


def incident_timings(inc):
    """Bir incident için Controller içi süreler (ms). Uçtan uca değildir."""
    steps = {}
    for s in inc.get("steps", []):
        steps.setdefault(s["step"], s["t"])

    def dt(a, b):
        if a in steps and b in steps:
            return round((steps[b] - steps[a]) * 1000, 1)
        return None

    return {
        "olay_id": inc.get("id"),
        "link": inc.get("link"),
        "durum": inc.get("status"),
        "tespit_epoch": steps.get("DETECTED"),
        "path_active_epoch": steps.get("PATH_ACTIVE"),
        "tespit_dogrulama_ms": dt("DETECTED", "CONFIRMED"),
        "tespit_yol_secimi_ms": dt("DETECTED", "ROUTE_SELECTED"),
        "tespit_flow_baslangic_ms": dt("DETECTED", "FLOW_INSTALL_START"),
        "tespit_path_active_ms": dt("DETECTED", "PATH_ACTIVE"),
        # LINK_UP -> FAILBACK_START kasıtlı kararlılık beklemesini içerir
        "linkup_failback_baslangic_ms": dt("LINK_UP", "FAILBACK_START"),
        "failback_islem_ms": dt("FAILBACK_START", "FAILBACK_COMPLETE"),
        "linkup_failback_tamam_ms": dt("LINK_UP", "FAILBACK_COMPLETE"),
    }


def select_incident(incidents, scenario, t_window=None):
    """Senaryoya uyan incident'i seçer. Döner: (incident|None, not)."""
    want = {"baglanti_kopmasi": "PATH_ACTIVE",
            "failback": "FAILBACK_COMPLETE"}.get(scenario)
    if want is None:
        return None, None
    cands = [i for i in incidents if i.get("kind") == "LINK_FAILURE"
             and any(s["step"] == want for s in i.get("steps", []))]
    if t_window is not None:
        lo, hi = t_window
        cands = [i for i in cands
                 if any(lo <= s["t"] <= hi for s in i.get("steps", [])
                        if s["step"] == want)]
        note = None if cands else ("ping zaman penceresinde %s olayı yok"
                                   % want)
    else:
        note = ("Controller olayı ping kaydıyla zamanca eşleştirilemedi "
                "(metin kaydında zaman yok); state kopyasındaki son %s olayı "
                "kullanıldı" % want) if cands else None
    if not cands:
        return None, note or ("state kopyasında %s içeren olay yok" % want)
    return cands[-1], note


# ----------------------------------------------------------------------
# Deney analizi
# ----------------------------------------------------------------------
def analyze(log, scenario=None, incidents=None):
    """ParsedLog'dan tek bir deney sonuç sözlüğü üretir."""
    scenario = scenario or log.meta.get("senaryo")
    recs = log.records
    notes = list(log.warnings)
    replies = [r for r in recs if r.status == REPLY]
    lost = [r for r in recs if r.status != REPLY]
    icmp_err = sum(1 for r in recs if r.status == ICMP_ERROR)
    observed = len(recs)

    expected = log.expected
    if expected is None and recs:
        expected = recs[-1].seq
        notes.append("beklenen paket sayısı bilinmiyor; en büyük seq (%d) "
                     "kullanıldı" % expected)
    seen = {r.seq for r in recs}
    missing = sorted(set(range(1, (expected or 0) + 1)) - seen)
    beyond = [s for s in seen if expected and s > expected]
    if missing:
        notes.append("kayıtta olmayan seq: %s" % _ranges(missing))
    if beyond:
        notes.append("beklenenden büyük seq: %s" % _ranges(beyond))
    if icmp_err:
        notes.append("%d paket ICMP hata mesajı ile döndü (kayıp sayıldı)"
                     % icmp_err)

    st = rtt_stats(recs)
    if (len(replies) >= 5 and replies[0].seq == 1 and st["medyan"]
            and replies[0].rtt_ms > 3 * st["medyan"]):
        notes.append("ilk paket RTT'si medyanın 3 katından büyük (ARP / ilk "
                     "akış kurulumu etkisi olabilir); dahil edildi")

    bursts = loss_bursts(recs)
    longest = max(bursts, key=lambda b: b[2]) if bursts else None
    interval_s = log.interval_ms / 1000.0

    res = {
        "deney_adi": log.meta.get("deney", ""),
        "tarih_saat": log.meta.get("tarih", ""),
        "senaryo": scenario or "",
        "tekrar": log.meta.get("tekrar", ""),
        "veri_kaynagi": log.source,
        "veri_turu": ("ORNEK" if log.meta.get("veri_turu", "").lower()
                      in ("ornek", "örnek", "sentetik") else "GERCEK_OLCUM"),
        "beklenen_paket": expected,
        "gonderilen_paket": observed,
        "basarili_paket": len(replies),
        "kayip_paket": len(lost),
        "eksik_seq_sayisi": len(missing),
        "kayip_yuzde": _r(100.0 * len(lost) / observed) if observed else None,
        "kayip_alt_yuzde": (_r(100.0 * len(lost) / expected)
                            if expected else None),
        "kayip_ust_yuzde": (_r(100.0 * (len(lost) + len(missing)) / expected)
                            if expected else None),
        "rtt_min_ms": _r(st["min"]), "rtt_max_ms": _r(st["max"]),
        "rtt_ort_ms": _r(st["ort"]), "rtt_medyan_ms": _r(st["medyan"]),
        "rtt_p95_ms": _r(st["p95"]), "rtt_std_ms": _r(st["std"]),
        "jitter_ms": _r(st["jitter"]),
        "kayip_patlamasi_sayisi": len(bursts),
        "en_uzun_kayip_patlamasi": longest[2] if longest else 0,
        "kesinti_baslangic_seq": longest[0] if longest else None,
        "kesinti_bitis_seq": longest[1] if longest else None,
        "kesinti_nominal_s": _r(longest[2] * interval_s) if longest else 0.0,
        "kesinti_olculen_s": None,
        "aralik_ms": log.interval_ms,
    }
    res.update(_segments(log, scenario, longest))
    if longest:
        res["kesinti_olculen_s"] = _measured_outage(recs, longest)

    res.update({k: None for k in CONTROLLER_COLUMNS})
    if incidents is not None and scenario in ("baglanti_kopmasi", "failback"):
        window = None
        times = [t for r in recs for t in (r.t_sent, r.t_reply) if t]
        if times:
            window = (min(times) - 1.0, max(times) + 1.0)
        inc, note = select_incident(incidents, scenario, window)
        if note:
            notes.append(note)
        if inc is not None:
            tm = incident_timings(inc)
            for k in CONTROLLER_COLUMNS:
                res[k] = tm.get(k.replace("ctrl_", "", 1))
            if longest and tm["path_active_epoch"] and times:
                res["path_active_ilk_yanit_ms"] = _first_reply_after(
                    recs, tm["path_active_epoch"])

    res["durum"] = _verdict(res, scenario, log, notes)
    res["notlar"] = " | ".join(notes)
    return res


CONTROLLER_COLUMNS = (
    "ctrl_olay_id", "ctrl_tespit_path_active_ms", "ctrl_tespit_flow_baslangic_ms",
    "ctrl_linkup_failback_baslangic_ms", "ctrl_failback_islem_ms",
)


def _segments(log, scenario, longest):
    """Arıza/olay öncesi ve sonrası RTT karşılaştırması."""
    out = {k: None for k in ("bolme_noktasi", "oncesi_paket", "oncesi_kayip",
                             "oncesi_rtt_ort_ms", "oncesi_rtt_medyan_ms",
                             "oncesi_rtt_p95_ms", "sonrasi_paket",
                             "sonrasi_kayip", "sonrasi_rtt_ort_ms",
                             "sonrasi_rtt_medyan_ms", "sonrasi_rtt_p95_ms",
                             "path_active_ilk_yanit_ms")}
    event_seq = log.meta.get("olay_ping", "")
    if longest and scenario not in STEADY_SCENARIOS:
        pre = [r for r in log.records if r.seq < longest[0]]
        post = [r for r in log.records if r.seq > longest[1]]
        out["bolme_noktasi"] = "kayip_patlamasi_%d-%d" % longest[:2]
    elif event_seq.isdigit():
        pre = [r for r in log.records if r.seq < int(event_seq)]
        post = [r for r in log.records if r.seq >= int(event_seq)]
        out["bolme_noktasi"] = "olay_ping_%s" % event_seq
    else:
        return out
    for name, part in (("oncesi", pre), ("sonrasi", post)):
        st = rtt_stats(part)
        out[name + "_paket"] = len(part)
        out[name + "_kayip"] = sum(1 for r in part if r.status != REPLY)
        out[name + "_rtt_ort_ms"] = _r(st["ort"])
        out[name + "_rtt_medyan_ms"] = _r(st["medyan"])
        out[name + "_rtt_p95_ms"] = _r(st["p95"])
    return out


def _measured_outage(records, burst):
    by_seq = {r.seq: r for r in records}
    before = by_seq.get(burst[0] - 1)
    after = by_seq.get(burst[1] + 1)
    if (before and after and before.t_reply and after.t_reply
            and before.status == REPLY and after.status == REPLY):
        return _r(after.t_reply - before.t_reply)
    return None


def _first_reply_after(records, t):
    later = [r.t_reply for r in records if r.status == REPLY and r.t_reply
             and r.t_reply >= t]
    return _r((min(later) - t) * 1000) if later else None


def _verdict(res, scenario, log, notes):
    """BASARILI / BASARISIZ / BELIRSIZ kararı ve gerekçesi."""
    if res["gonderilen_paket"] == 0:
        if log.meta.get("not_reachable"):
            return "BASARISIZ"
        notes.append("hiç ping kaydı bulunamadı")
        return "BELIRSIZ"
    if res["eksik_seq_sayisi"] or any("birden fazla" in n for n in notes):
        return "BELIRSIZ"
    if scenario in STEADY_SCENARIOS or not scenario:
        return "BASARILI" if res["kayip_paket"] == 0 else "BASARISIZ"
    # Geçici kesinti beklenen senaryolar: iletişim sonunda yeniden kurulmalı
    if log.records[-1].status != REPLY:
        notes.append("kayıt kayıpla bitiyor: iletişim yeniden kurulmadı")
        return "BASARISIZ"
    if res["kayip_paket"] == 0 and scenario == "baglanti_kopmasi":
        notes.append("kayıp gözlenmedi; link gerçekten kesildi mi doğrulayın")
    return "BASARILI"


def _r(v, nd=3):
    return None if v is None else round(v, nd)


def analyze_files(text_path=None, pcap_path=None, state_path=None,
                  scenario=None, target=DEFAULT_DST, src=DEFAULT_SRC):
    """Dosyalardan tek deney analizi. pcap varsa zaman damgalı birincil kaynak
    olur; metin kaydı meta veri ve çapraz kontrol için kullanılır."""
    text_log = None
    if text_path:
        with open(text_path, encoding="utf-8", errors="replace") as f:
            text_log = parse_ping_text(f.read(), target)
    log = text_log
    if pcap_path:
        log = read_pcap_icmp(pcap_path, src, target)
        if text_log is not None:
            log.meta = dict(text_log.meta, **log.meta)
            log.interval_ms = text_log.interval_ms
            log.expected = text_log.expected
            t_ok = sum(1 for r in text_log.records if r.status == REPLY)
            p_ok = sum(1 for r in log.records if r.status == REPLY)
            if text_log.records and t_ok != p_ok:
                log.warnings.append("metin (%d yanıt) ile pcap (%d yanıt) "
                                    "uyuşmuyor" % (t_ok, p_ok))
        if log.expected is None:
            log.expected = len(log.records)
    if log is None:
        raise MeasurementError("metin veya pcap dosyası verilmeli")
    incidents = load_incidents(state_path) if state_path else None
    return analyze(log, scenario, incidents)


# ----------------------------------------------------------------------
# Komut satırı
# ----------------------------------------------------------------------
def format_report(res):
    lines = ["Deney        : %s (%s, tekrar %s)" % (res["deney_adi"] or "-",
                                                    res["senaryo"] or "-",
                                                    res["tekrar"] or "-"),
             "Veri         : %s / %s" % (res["veri_kaynagi"], res["veri_turu"]),
             "Paket        : beklenen=%s gönderilen(gözlenen)=%s başarılı=%s "
             "kayıp=%s eksik=%s" % (res["beklenen_paket"],
                                    res["gonderilen_paket"],
                                    res["basarili_paket"], res["kayip_paket"],
                                    res["eksik_seq_sayisi"]),
             "Kayıp        : %%%s (alt %%%s, üst %%%s)" % (
                 res["kayip_yuzde"], res["kayip_alt_yuzde"],
                 res["kayip_ust_yuzde"]),
             "RTT (ms)     : min=%s ort=%s medyan=%s p95=%s max=%s std=%s" % (
                 res["rtt_min_ms"], res["rtt_ort_ms"], res["rtt_medyan_ms"],
                 res["rtt_p95_ms"], res["rtt_max_ms"], res["rtt_std_ms"]),
             "Jitter (ms)  : %s  (ardışık seq |ΔRTT| ortalaması)"
             % res["jitter_ms"],
             "Kesinti      : en uzun %s paket (seq %s-%s), nominal %s s, "
             "ölçülen %s s" % (res["en_uzun_kayip_patlamasi"],
                               res["kesinti_baslangic_seq"],
                               res["kesinti_bitis_seq"],
                               res["kesinti_nominal_s"],
                               res["kesinti_olculen_s"])]
    if res["bolme_noktasi"]:
        lines.append("Önce/Sonra   : [%s] önce ort=%s p95=%s (n=%s) | sonra "
                     "ort=%s p95=%s (n=%s)" % (
                         res["bolme_noktasi"], res["oncesi_rtt_ort_ms"],
                         res["oncesi_rtt_p95_ms"], res["oncesi_paket"],
                         res["sonrasi_rtt_ort_ms"], res["sonrasi_rtt_p95_ms"],
                         res["sonrasi_paket"]))
    if res["ctrl_olay_id"] is not None:
        lines.append("Controller   : olay #%s tespit->PATH_ACTIVE=%s ms, "
                     "failback işlem=%s ms (Controller içi; uçtan uca DEĞİL)"
                     % (res["ctrl_olay_id"], res["ctrl_tespit_path_active_ms"],
                        res["ctrl_failback_islem_ms"]))
    lines.append("Durum        : %s" % res["durum"])
    if res["notlar"]:
        lines.append("Notlar       : %s" % res["notlar"])
    return "\n".join(lines)


def format_incidents(incidents):
    rows = ["%-4s %-16s %9s %9s %9s %11s %9s  %s" % (
        "id", "durum", "dogrula", "yol", "flow_bas", "PATH_ACTIVE",
        "fb_islem", "link")]
    for inc in incidents:
        tm = incident_timings(inc)
        rows.append("%-4s %-16s %9s %9s %9s %11s %9s  %s" % (
            tm["olay_id"], tm["durum"], tm["tespit_dogrulama_ms"],
            tm["tespit_yol_secimi_ms"], tm["tespit_flow_baslangic_ms"],
            tm["tespit_path_active_ms"], tm["failback_islem_ms"], tm["link"]))
    rows.append("(ms; DETECTED anına göre. Controller içi süreler - uçtan uca "
                "paket kesintisi değildir.)")
    return "\n".join(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description="PC1->PC2 ping deney analizi "
                                "(Aşama 8.5). Ağa trafik göndermez.")
    p.add_argument("metin", nargs="?", help="VPCS ping çıktısı (.txt)")
    p.add_argument("--pcap", help="isteğe bağlı pcap (zaman damgalı kaynak)")
    p.add_argument("--state", help="runtime/state.json kopyası")
    p.add_argument("--senaryo", choices=sorted(SCENARIOS))
    p.add_argument("--hedef", default=DEFAULT_DST)
    p.add_argument("--kaynak", default=DEFAULT_SRC)
    p.add_argument("--controller-olaylari", metavar="STATE_JSON",
                   help="yalnız Controller olay sürelerini listele")
    a = p.parse_args(argv)
    if a.controller_olaylari:
        print(format_incidents(load_incidents(a.controller_olaylari)))
        return 0
    if not a.metin and not a.pcap:
        p.error("metin dosyası veya --pcap gerekli")
    try:
        res = analyze_files(a.metin, a.pcap, a.state, a.senaryo, a.hedef,
                            a.kaynak)
    except MeasurementError as e:
        print("ÖLÇÜM YAPILAMADI: %s" % e, file=sys.stderr)
        return 2
    print(format_report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
