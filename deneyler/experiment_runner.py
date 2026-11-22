"""
Aşama 8.5 - Tekrarlı deney yöneticisi (4 senaryo x 3 tekrar).

Bu betik ağa ping GÖNDERMEZ, VPCS konsoluna BAĞLANMAZ ve hiçbir servisi
başlatıp durdurmaz. VPCS konsolu (5000/5001) tek istemci kabul eder ve bu
bağlantı GNS3 Server'a aittir; araya girmek kullanıcının oturumunu bozar.
Bu nedenle ping'ler GNS3 konsolundan elle başlatılır, betik ise:

  plan          Deney planını ve hangi kayıtların hazır olduğunu gösterir
  portlar       PC1/PC2 VPCS UDP tünel portlarını (ps, salt okunur) bulur ve
                isteğe bağlı tcpdump komutunu yazdırır
  yeni          Bir deney için başlıklı boş kayıt şablonu oluşturur
  state-kopyala runtime/state.json'ın o deneye ait bir KOPYASINI alır
  analiz        ham_veri/ altındaki tüm kayıtları analiz eder; CSV + SVG üretir

Kullanım (proje kökünden):
    python3 deneyler/experiment_runner.py plan
    python3 deneyler/experiment_runner.py yeni baglanti_kopmasi 1
    python3 deneyler/experiment_runner.py state-kopyala baglanti_kopmasi 1
    python3 deneyler/experiment_runner.py analiz
"""

import argparse
import csv
import datetime
import os
import re
import shutil
import statistics
import subprocess
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ping_analyzer import (SCENARIOS, MeasurementError,  # noqa: E402
                           analyze, analyze_files, parse_ping_text,
                           load_incidents, format_report)

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
RAW_DIR = os.path.join(HERE, "ham_veri")
OUT_DIR = os.path.join(HERE, "sonuclar")
STATE_JSON = os.path.join(PROJECT, "runtime", "state.json")
REPEATS = 3
DEFAULT_COUNT = 100

STEPS = {
    "normal": [
        "Topoloji sağlıklı: Dashboard'da 4 switch / 4 bağlantı, 0 arıza.",
        "PC1 konsolu: ping 10.0.0.2 -c 100",
        "Ping bitince çıktıyı kayıt dosyasına yapıştır.",
    ],
    "baglanti_kopmasi": [
        "Topoloji sağlıklı (4/4). PC1 konsolu: ping 10.0.0.2 -c 100",
        "Yaklaşık 30. ping'te OVS-1 <-> OVS-2 linkini GNS3'te Suspend et;"
        " o anki seq'i 'olay_ping' başlığına yaz.",
        "Link KOPUK kalsın; ping bitince çıktıyı yapıştır.",
        "Hemen state-kopyala çalıştır (Controller tepki süresi için).",
    ],
    "otomatik_kurtarma": [
        "Önceki adımdaki link hâlâ Suspend; Dashboard'da recovery yolu"
        " (PATH_ACTIVE) aktif olmalı.",
        "PC1 konsolu: ping 10.0.0.2 -c 100 (alternatif yol kararlı durumu).",
        "Ping bitince çıktıyı yapıştır; state-kopyala çalıştır.",
    ],
    "failback": [
        "Link hâlâ Suspend iken PC1 konsolu: ping 10.0.0.2 -c 100",
        "Yaklaşık 30. ping'te linki Resume et; seq'i 'olay_ping' başlığına"
        " yaz.",
        "FAILBACK_COMPLETE için Resume sonrası en az ~15 sn ping sürmeli.",
        "Ping bitince çıktıyı yapıştır; state-kopyala çalıştır.",
    ],
}

RESULT_COLUMNS = [
    "deney_adi", "tarih_saat", "senaryo", "tekrar", "veri_kaynagi",
    "veri_turu", "durum", "beklenen_paket", "gonderilen_paket",
    "basarili_paket", "kayip_paket", "eksik_seq_sayisi", "kayip_yuzde",
    "kayip_alt_yuzde", "kayip_ust_yuzde", "rtt_min_ms", "rtt_max_ms",
    "rtt_ort_ms", "rtt_medyan_ms", "rtt_p95_ms", "rtt_std_ms", "jitter_ms",
    "kayip_patlamasi_sayisi", "en_uzun_kayip_patlamasi",
    "kesinti_baslangic_seq", "kesinti_bitis_seq", "kesinti_nominal_s",
    "kesinti_olculen_s", "aralik_ms", "bolme_noktasi", "oncesi_paket",
    "oncesi_kayip", "oncesi_rtt_ort_ms", "oncesi_rtt_medyan_ms",
    "oncesi_rtt_p95_ms", "sonrasi_paket", "sonrasi_kayip",
    "sonrasi_rtt_ort_ms", "sonrasi_rtt_medyan_ms", "sonrasi_rtt_p95_ms",
    "ctrl_olay_id", "ctrl_tespit_path_active_ms",
    "ctrl_tespit_flow_baslangic_ms", "ctrl_linkup_failback_baslangic_ms",
    "ctrl_failback_islem_ms", "path_active_ilk_yanit_ms", "kaynak_dosya",
    "notlar",
]

SUMMARY_METRICS = [
    "kayip_yuzde", "rtt_ort_ms", "rtt_medyan_ms", "rtt_p95_ms", "jitter_ms",
    "en_uzun_kayip_patlamasi", "kesinti_nominal_s", "kesinti_olculen_s",
    "ctrl_tespit_path_active_ms", "ctrl_failback_islem_ms",
]

# (metrik, başlık, birim) - her metrik ayrı grafik (tek eksen kuralı)
CHARTS = [
    ("kayip_yuzde", "Paket kaybı", "%"),
    ("rtt_ort_ms", "Ortalama RTT", "ms"),
    ("rtt_p95_ms", "P95 RTT", "ms"),
    ("jitter_ms", "Jitter (ardışık |ΔRTT| ort.)", "ms"),
    ("en_uzun_kayip_patlamasi", "En uzun kesinti", "paket"),
]
# Senaryo kimliği tüm grafiklerde aynı renk (sabit sıra, döngü yok)
COLORS = {"normal": "#2a78d6", "baglanti_kopmasi": "#eb6834",
          "otomatik_kurtarma": "#1baf7a", "failback": "#eda100"}


def base_name(scenario, rep):
    return "%s_t%d" % (scenario, rep)


# ----------------------------------------------------------------------
# plan / yeni / state-kopyala / portlar
# ----------------------------------------------------------------------
def cmd_plan(raw_dir):
    print("Aşama 8.5 deney planı: %d senaryo x %d tekrar, PC1 -> PC2\n"
          % (len(SCENARIOS), REPEATS))
    for i, (sc, title) in enumerate(SCENARIOS.items(), 1):
        print("%d. %s  [%s]" % (i, title, sc))
        for step in STEPS[sc]:
            print("     - %s" % step)
        for rep in range(1, REPEATS + 1):
            b = os.path.join(raw_dir, base_name(sc, rep))
            print("     tekrar %d: metin=%s pcap=%s state=%s" % (
                rep, _status(b + ".txt"), _mark(b + ".pcap"),
                _mark(b + "_state.json")))
        print()
    print("Kayıt sırası önerisi: normal -> baglanti_kopmasi -> "
          "otomatik_kurtarma -> failback; her tekrar için döngüyü baştan "
          "uygulayın.")


def _mark(path):
    return "var" if os.path.exists(path) else "-"


def _status(path):
    if not os.path.exists(path):
        return "-"
    with open(path, encoding="utf-8", errors="replace") as f:
        log = parse_ping_text(f.read())
    return "%d kayıt" % len(log.records) if log.records else "şablon(boş)"


def cmd_new(raw_dir, scenario, rep, count):
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, base_name(scenario, rep) + ".txt")
    if os.path.exists(path):
        print("ZATEN VAR, üzerine yazılmadı: %s" % path)
        return 1
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "# deney: %s\n# senaryo: %s\n# tekrar: %d\n# tarih: %s\n"
            "# paket_sayisi: %d\n# aralik_ms: 1000\n# olay_ping: \n"
            "# veri_turu: gercek\n# not: \n"
            "# (olay_ping = Suspend/Resume anındaki icmp_seq; normal ve\n"
            "#  otomatik_kurtarma için boş bırakın)\n"
            "# ---- VPCS çıktısını (ping komutu dahil) bu satırın ALTINA"
            " yapıştırın ----\n" % (base_name(scenario, rep), scenario, rep,
                                    now, count))
    print("Şablon oluşturuldu: %s" % path)
    print("PC1 konsolunda çalıştırın: ping 10.0.0.2 -c %d" % count)
    for step in STEPS[scenario]:
        print("  - %s" % step)
    return 0


def cmd_copy_state(raw_dir, scenario, rep, state_path=STATE_JSON):
    os.makedirs(raw_dir, exist_ok=True)
    dst = os.path.join(raw_dir, base_name(scenario, rep) + "_state.json")
    if os.path.exists(dst):
        print("ZATEN VAR, üzerine yazılmadı: %s" % dst)
        return 1
    if not os.path.exists(state_path):
        print("state.json bulunamadı: %s" % state_path)
        return 1
    shutil.copyfile(state_path, dst)   # kaynak yalnız okunur
    print("Kopyalandı: %s (%d olay)" % (dst, len(load_incidents(dst))))
    return 0


VPCS_RE = re.compile(r"vpcs\s.*-p\s+(\d+).*-s\s+(\d+)\s+-c\s+(\d+)")


def find_vpcs_ports():
    """{konsol_portu: (vpcs_udp, ubridge_udp)} - yalnız ps çıktısı okunur."""
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                         text=True, check=False).stdout
    ports = {}
    for line in out.splitlines():
        m = VPCS_RE.search(line)
        if m:
            ports[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
    return ports


def cmd_ports():
    ports = find_vpcs_ports()
    if not ports:
        print("Çalışan VPCS süreci bulunamadı.")
        return 1
    for console, (s, c) in sorted(ports.items()):
        name = {5000: "PC1", 5001: "PC2"}.get(console, "?")
        print("%s konsol=%d  VPCS UDP=%d  ubridge UDP=%d" % (name, console,
                                                             s, c))
    if 5000 in ports:
        s, c = ports[5000]
        print("\nİsteğe bağlı paket yakalama (PC1 tüneli, ayrı terminalde,"
              " ping'ten ÖNCE başlatın, bitince Ctrl+C):")
        print("  sudo tcpdump -i lo -U -Z $USER -w deneyler/ham_veri/"
              "<senaryo>_t<n>.pcap 'udp port %d or udp port %d'" % (s, c))
        print("Önce kısa bir denemeyle ICMP görüldüğünü doğrulayın:")
        print("  python3 deneyler/ping_analyzer.py --pcap deneme.pcap")
        print("(GNS3 yeniden başlarsa portlar değişebilir; komutu tekrar"
              " çalıştırın.)")
    return 0


# ----------------------------------------------------------------------
# analiz
# ----------------------------------------------------------------------
def analyze_dir(raw_dir):
    results = []
    if not os.path.isdir(raw_dir):
        return results
    for name in sorted(os.listdir(raw_dir)):
        if not name.endswith(".txt"):
            continue
        base = os.path.join(raw_dir, name[:-4])
        pcap = base + ".pcap" if os.path.exists(base + ".pcap") else None
        state = (base + "_state.json"
                 if os.path.exists(base + "_state.json") else None)
        scenario = _scenario_from_name(name)
        try:
            res = analyze_files(base + ".txt", pcap, state, scenario)
        except MeasurementError as e:
            # pcap güvenilmezse metin kaydına dön ve bunu not et
            with open(base + ".txt", encoding="utf-8",
                      errors="replace") as f:
                log = parse_ping_text(f.read())
            log.warnings.append("pcap kullanılamadı: %s" % e)
            res = analyze(log, scenario,
                          load_incidents(state) if state else None)
        res["kaynak_dosya"] = os.path.relpath(base + ".txt", PROJECT)
        if res["gonderilen_paket"] == 0 and not res["veri_turu"] == "ORNEK":
            res["notlar"] = "henüz veri yok (boş şablon)"
        results.append(res)
    return results


def _scenario_from_name(name):
    for sc in SCENARIOS:
        if name.startswith(sc + "_"):
            return sc
    return None


def write_results_csv(results, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow({k: "" if r.get(k) is None else r.get(k)
                        for k in RESULT_COLUMNS})


def summarize(results):
    """Senaryo bazında tekrarlar üzerinden ortalama / std / min / max."""
    rows = []
    for sc in SCENARIOS:
        rs = [r for r in results if r["senaryo"] == sc
              and r["gonderilen_paket"]]
        if not rs:
            continue
        row = {"senaryo": sc, "tekrar_sayisi": len(rs),
               "veri_turu": ",".join(sorted({r["veri_turu"] for r in rs}))}
        for d in ("BASARILI", "BASARISIZ", "BELIRSIZ"):
            row[d.lower()] = sum(1 for r in rs if r["durum"] == d)
        for m in SUMMARY_METRICS:
            vals = [r[m] for r in rs if r.get(m) is not None]
            row[m + "_n"] = len(vals)
            row[m + "_ort"] = round(statistics.mean(vals), 3) if vals else ""
            row[m + "_std"] = (round(statistics.stdev(vals), 3)
                               if len(vals) > 1 else "")
            row[m + "_min"] = min(vals) if vals else ""
            row[m + "_max"] = max(vals) if vals else ""
        rows.append(row)
    return rows


def write_summary_csv(rows, path):
    cols = ["senaryo", "tekrar_sayisi", "veri_turu", "basarili", "basarisiz",
            "belirsiz"]
    for m in SUMMARY_METRICS:
        cols += [m + s for s in ("_n", "_ort", "_std", "_min", "_max")]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def svg_bar_chart(results, metric, title, unit, sample=False):
    """Senaryo başına tekrar ortalaması (çubuk) + her tekrar (nokta)."""
    groups = [(sc, [r[metric] for r in results if r["senaryo"] == sc
                    and r.get(metric) is not None])
              for sc in SCENARIOS]
    groups = [(sc, v) for sc, v in groups if v]
    if not groups:
        return None
    W, H, L, R, T, B = 640, 360, 64, 20, 64, 72
    pw, ph = W - L - R, H - T - B
    top = max(max(v) for _, v in groups) or 1.0
    top = _nice_ceiling(top)
    y = lambda v: T + ph - ph * v / top          # noqa: E731
    slot = pw / len(groups)
    bw = min(72, slot * 0.5)
    ink, muted, grid = "#0b0b0b", "#5f5e5a", "#e4e3df"
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'viewBox="0 0 %d %d" font-family="Helvetica, Arial, sans-serif">'
         % (W, H, W, H),
         '<rect width="100%%" height="100%%" fill="#fcfcfb"/>',
         '<text x="%d" y="26" font-size="16" font-weight="600" fill="%s">'
         '%s (%s)</text>' % (L, ink, escape(title), escape(unit)),
         '<text x="%d" y="46" font-size="11" fill="%s">Çubuk: tekrar '
         'ortalaması · nokta: tek tekrar · PC1 → PC2</text>' % (L, muted)]
    if sample:
        o.append('<text x="%d" y="26" font-size="12" font-weight="700" '
                 'fill="#b3261e" text-anchor="end">ÖRNEK VERİ – gerçek ölçüm '
                 'değildir</text>' % (W - R))
    for i in range(5):
        v = top * i / 4
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/>'
                 % (L, W - R, y(v), y(v), grid if i else muted))
        o.append('<text x="%d" y="%.1f" font-size="11" fill="%s" '
                 'text-anchor="end">%s</text>' % (L - 8, y(v) + 4, muted,
                                                  _fmt(v)))
    for k, (sc, vals) in enumerate(groups):
        cx = L + slot * (k + 0.5)
        mean = statistics.mean(vals)
        color = COLORS[sc]
        h = max(T + ph - y(mean), 0)
        tip = "%s: ort %s %s (n=%d; %s)" % (
            SCENARIOS[sc], _fmt(mean), unit, len(vals),
            ", ".join(_fmt(v) for v in vals))
        o.append('<g><title>%s</title>' % escape(tip))
        o.append('<path d="M%.1f %.1f v%.1f a4 4 0 0 1 4 -4 h%.1f a4 4 0 0 1 '
                 '4 4 v%.1f z" fill="%s" fill-opacity="0.85"/>' % (
                     cx - bw / 2, T + ph, -max(h - 4, 0), bw - 8,
                     max(h - 4, 0), color) if h > 4 else
                 '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                 'fill="%s"/>' % (cx - bw / 2, T + ph - h, bw, h, color))
        for j, v in enumerate(vals):
            dx = (j - (len(vals) - 1) / 2) * 12
            o.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="%s" '
                     'stroke="#fcfcfb" stroke-width="2"/>' % (cx + dx, y(v),
                                                               ink))
        o.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="600" '
                 'fill="%s" text-anchor="middle">%s</text>' % (
                     cx, min(y(mean), y(max(vals))) - 10, ink, _fmt(mean)))
        o.append('<text x="%.1f" y="%d" font-size="11" fill="%s" '
                 'text-anchor="middle">%s</text>' % (cx, T + ph + 18, ink,
                                                      escape(sc)))
        o.append('<text x="%.1f" y="%d" font-size="10" fill="%s" '
                 'text-anchor="middle">n=%d</text></g>' % (
                     cx, T + ph + 34, muted, len(vals)))
    o.append("</svg>")
    return "\n".join(o)


def _nice_ceiling(v):
    import math
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def _fmt(v):
    return ("%.0f" % v if abs(v) >= 100 else "%.1f" % v if abs(v) >= 10
            else "%.2f" % v)


def write_outputs(results, out_dir, include_sample=False):
    """CSV ve grafikleri yazar. Varsayılan olarak ORNEK veriler özet ve
    grafiklere girmez; yalnız deney_sonuclari.csv'de veri_turu ile görünür."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    p = os.path.join(out_dir, "deney_sonuclari.csv")
    write_results_csv(results, p)
    written.append(p)
    usable = [r for r in results if r["gonderilen_paket"]
              and (include_sample or r["veri_turu"] == "GERCEK_OLCUM")]
    if not usable:
        return written
    sample = any(r["veri_turu"] == "ORNEK" for r in usable)
    p = os.path.join(out_dir, "senaryo_ozeti.csv")
    write_summary_csv(summarize(usable), p)
    written.append(p)
    for metric, title, unit in CHARTS:
        svg = svg_bar_chart(usable, metric, title, unit, sample)
        if svg:
            p = os.path.join(out_dir, "grafik_%s.svg" % metric)
            with open(p, "w", encoding="utf-8") as f:
                f.write(svg)
            written.append(p)
    return written


def cmd_analyze(raw_dir, out_dir, verbose):
    results = analyze_dir(raw_dir)
    if not results:
        print("Analiz edilecek kayıt yok (%s). Önce: experiment_runner.py "
              "yeni <senaryo> <tekrar>" % raw_dir)
        return 1
    for r in results:
        if verbose:
            print(format_report(r) + "\n")
        else:
            print("%-22s %-10s kayıp=%s%% ort=%s ms p95=%s ms kesinti=%s pkt"
                  % (r["deney_adi"] or r["kaynak_dosya"], r["durum"],
                     r["kayip_yuzde"], r["rtt_ort_ms"], r["rtt_p95_ms"],
                     r["en_uzun_kayip_patlamasi"]))
    for p in write_outputs(results, out_dir):
        print("yazıldı: %s" % os.path.relpath(p, PROJECT))
    real = sum(1 for r in results if r["veri_turu"] == "GERCEK_OLCUM"
               and r["gonderilen_paket"])
    print("Gerçek ölçüm içeren kayıt: %d / hedef %d" % (
        real, len(SCENARIOS) * REPEATS))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ham-dizin", default=RAW_DIR)
    p.add_argument("--cikti-dizin", default=OUT_DIR)
    sub = p.add_subparsers(dest="komut", required=True)
    sub.add_parser("plan")
    sub.add_parser("portlar")
    for name in ("yeni", "state-kopyala"):
        s = sub.add_parser(name)
        s.add_argument("senaryo", choices=list(SCENARIOS))
        s.add_argument("tekrar", type=int, choices=range(1, REPEATS + 1))
        if name == "yeni":
            s.add_argument("--paket", type=int, default=DEFAULT_COUNT)
    s = sub.add_parser("analiz")
    s.add_argument("-v", "--ayrintili", action="store_true")
    a = p.parse_args(argv)
    if a.komut == "plan":
        return cmd_plan(a.ham_dizin) or 0
    if a.komut == "portlar":
        return cmd_ports()
    if a.komut == "yeni":
        return cmd_new(a.ham_dizin, a.senaryo, a.tekrar, a.paket)
    if a.komut == "state-kopyala":
        return cmd_copy_state(a.ham_dizin, a.senaryo, a.tekrar)
    return cmd_analyze(a.ham_dizin, a.cikti_dizin, a.ayrintili)


if __name__ == "__main__":
    sys.exit(main())
