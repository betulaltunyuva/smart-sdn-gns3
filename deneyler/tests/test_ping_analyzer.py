"""
Aşama 8.5 - ping_analyzer ve experiment_runner offline testleri.

Buradaki TÜM ping kayıtları ve pcap'ler test için üretilmiş SENTETİK
verilerdir; gerçek ölçüm değildir ve sonuç raporlarında kullanılmaz.
GNS3, VPCS veya Controller gerekmez; yalnız geçici dizinlere yazılır.

Çalıştırma (proje kökünden):
    python3 -m unittest discover -v -s deneyler/tests
"""

import csv
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
import ping_analyzer as pa  # noqa: E402
import experiment_runner as er  # noqa: E402


def vpcs_reply(seq, rtt, ip="10.0.0.2"):
    return "84 bytes from %s icmp_seq=%d ttl=64 time=%.3f ms" % (ip, seq, rtt)


def vpcs_timeout(seq, ip="10.0.0.2"):
    return "%s icmp_seq=%d timeout" % (ip, seq)


def sample_text(lines, header=None, cmd="PC1> ping 10.0.0.2 -c %d"):
    head = ["# veri_turu: ornek"] + (header or [])
    if cmd:
        head.append(cmd % len(lines) if "%d" in cmd else cmd)
    return "\n".join(head + lines) + "\n"


def failure_run(n=100, lost=range(31, 36), rtt=4.0):
    return [vpcs_timeout(s) if s in lost else vpcs_reply(s, rtt + (s % 3))
            for s in range(1, n + 1)]


class ParseAndStatsTest(unittest.TestCase):
    def test_normal_all_replies(self):
        rtts = [3.0, 5.0, 4.0, 6.0, 2.0]
        log = pa.parse_ping_text(sample_text(
            [vpcs_reply(i + 1, r) for i, r in enumerate(rtts)]))
        res = pa.analyze(log, "normal")
        self.assertEqual(res["beklenen_paket"], 5)
        self.assertEqual(res["gonderilen_paket"], 5)
        self.assertEqual(res["basarili_paket"], 5)
        self.assertEqual(res["kayip_paket"], 0)
        self.assertEqual(res["kayip_yuzde"], 0.0)
        self.assertEqual(res["rtt_min_ms"], 2.0)
        self.assertEqual(res["rtt_max_ms"], 6.0)
        self.assertEqual(res["rtt_ort_ms"], 4.0)
        self.assertEqual(res["rtt_medyan_ms"], 4.0)
        self.assertEqual(res["rtt_p95_ms"], 6.0)
        # |5-3|,|4-5|,|6-4|,|2-6| = 2,1,2,4 -> 2.25
        self.assertEqual(res["jitter_ms"], 2.25)
        self.assertEqual(res["durum"], "BASARILI")
        self.assertEqual(res["veri_turu"], "ORNEK")

    def test_percentile_nearest_rank(self):
        vals = list(range(1, 21))           # 1..20
        self.assertEqual(pa.percentile_nearest_rank(vals, 95), 19)
        self.assertEqual(pa.percentile_nearest_rank(vals, 50), 10)
        self.assertEqual(pa.percentile_nearest_rank([7.0], 95), 7.0)
        self.assertIsNone(pa.percentile_nearest_rank([], 95))

    def test_jitter_skips_pairs_across_loss(self):
        recs = [pa.PingRecord(1, pa.REPLY, 1.0), pa.PingRecord(2, pa.TIMEOUT),
                pa.PingRecord(3, pa.REPLY, 50.0), pa.PingRecord(4, pa.REPLY,
                                                                52.0)]
        self.assertEqual(pa.jitter_ms(recs), 2.0)     # yalnız (3,4)

    def test_failure_burst_and_pre_post(self):
        log = pa.parse_ping_text(sample_text(failure_run(),
                                             ["# olay_ping: 31"]))
        res = pa.analyze(log, "baglanti_kopmasi")
        self.assertEqual(res["kayip_paket"], 5)
        self.assertEqual(res["kayip_yuzde"], 5.0)
        self.assertEqual(res["en_uzun_kayip_patlamasi"], 5)
        self.assertEqual((res["kesinti_baslangic_seq"],
                          res["kesinti_bitis_seq"]), (31, 35))
        self.assertEqual(res["kesinti_nominal_s"], 5.0)
        self.assertIsNone(res["kesinti_olculen_s"])   # metinde zaman yok
        self.assertEqual(res["oncesi_paket"], 30)
        self.assertEqual(res["sonrasi_paket"], 65)
        self.assertEqual(res["durum"], "BASARILI")

    def test_missing_seq_is_not_loss_and_marks_uncertain(self):
        lines = [l for l in failure_run(20, lost=[10])
                 if "icmp_seq=5 " not in l and "icmp_seq=6 " not in l]
        log = pa.parse_ping_text(sample_text(lines,
                                             cmd="ping 10.0.0.2 -c 20"))
        res = pa.analyze(log, "normal")
        self.assertEqual(res["eksik_seq_sayisi"], 2)
        self.assertEqual(res["kayip_paket"], 1)
        self.assertEqual(res["gonderilen_paket"], 18)
        self.assertEqual(res["kayip_alt_yuzde"], 5.0)    # 1/20
        self.assertEqual(res["kayip_ust_yuzde"], 15.0)   # 3/20
        self.assertEqual(res["durum"], "BELIRSIZ")
        self.assertIn("5-6", res["notlar"])

    def test_truncated_log_is_uncertain(self):
        lines = failure_run(100)[:60]
        log = pa.parse_ping_text(sample_text(lines,
                                             cmd="ping 10.0.0.2 -c 100"))
        res = pa.analyze(log, "baglanti_kopmasi")
        self.assertEqual(res["eksik_seq_sayisi"], 40)
        self.assertEqual(res["durum"], "BELIRSIZ")

    def test_duplicate_seq_two_sessions(self):
        lines = [vpcs_reply(s, 3) for s in (1, 2, 3)] * 2
        log = pa.parse_ping_text(sample_text(lines, cmd=None))
        res = pa.analyze(log, "normal")
        self.assertEqual(res["gonderilen_paket"], 3)
        self.assertEqual(res["durum"], "BELIRSIZ")

    def test_failback_ending_in_loss_fails(self):
        lines = failure_run(20, lost=range(15, 21))
        res = pa.analyze(pa.parse_ping_text(sample_text(lines)), "failback")
        self.assertEqual(res["durum"], "BASARISIZ")
        self.assertIn("yeniden kurulmadı", res["notlar"])

    def test_loss_in_steady_scenario_fails(self):
        res = pa.analyze(pa.parse_ping_text(sample_text(
            failure_run(10, lost=[4]))), "otomatik_kurtarma")
        self.assertEqual(res["durum"], "BASARISIZ")

    def test_not_reachable(self):
        log = pa.parse_ping_text("ping 10.0.0.2 -c 5\nhost (10.0.0.2) not "
                                 "reachable\n")
        res = pa.analyze(log, "normal")
        self.assertEqual(res["gonderilen_paket"], 0)
        self.assertEqual(res["durum"], "BASARISIZ")

    def test_empty_template_is_uncertain(self):
        res = pa.analyze(pa.parse_ping_text("# senaryo: normal\n"), None)
        self.assertEqual(res["durum"], "BELIRSIZ")

    def test_icmp_error_dup_other_target_garbage(self):
        lines = [vpcs_reply(1, 3.0),
                 "*10.0.0.254 icmp_seq=2 ttl=255 time=1.0 ms (ICMP type:3, "
                 "code:1, Destination host unreachable)",
                 vpcs_reply(3, 4.0),
                 vpcs_reply(3, 9.0) + " (DUP!)",
                 vpcs_reply(4, 1.0, ip="10.0.0.9"),
                 "garbled icmp_seq=?? xx",
                 vpcs_reply(4, 5.0)]
        log = pa.parse_ping_text(sample_text(lines, cmd="ping 10.0.0.2 -c 4"),
                                 target="10.0.0.2")
        res = pa.analyze(log, "normal")
        # ICMP hata satırı 10.0.0.254'ten geldiği için hedef dışı sayılır ->
        # seq 2 eksik kalır ve ölçüm belirsiz olur
        self.assertEqual(res["basarili_paket"], 3)
        self.assertEqual(res["eksik_seq_sayisi"], 1)
        self.assertEqual(res["rtt_max_ms"], 5.0)      # DUP satırı alınmadı
        self.assertEqual(res["durum"], "BELIRSIZ")
        self.assertIn("tanınmadı", res["notlar"])
        self.assertIn("farklı hedef", res["notlar"])

    def test_icmp_error_from_target_counted_as_loss(self):
        lines = [vpcs_reply(1, 3.0),
                 "*10.0.0.2 icmp_seq=2 ttl=64 time=1.0 ms (ICMP type:3, "
                 "code:3, Destination port unreachable)",
                 vpcs_reply(3, 4.0)]
        res = pa.analyze(pa.parse_ping_text(sample_text(lines)), "normal")
        self.assertEqual(res["kayip_paket"], 1)
        self.assertIn("ICMP hata", res["notlar"])

    def test_header_and_command_conflict(self):
        log = pa.parse_ping_text(sample_text(
            [vpcs_reply(1, 3.0)], ["# paket_sayisi: 100", "# aralik_ms: 500"],
            cmd="ping 10.0.0.2 -c 1"))
        self.assertEqual(log.expected, 1)
        self.assertEqual(log.interval_ms, 500.0)
        self.assertTrue(any("farklı" in w for w in log.warnings))


# ----------------------------------------------------------------------
# Sentetik pcap
# ----------------------------------------------------------------------
def _ip(src, dst, proto, payload):
    s = bytes(int(x) for x in src.split("."))
    d = bytes(int(x) for x in dst.split("."))
    return struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 0, 0, 64,
                       proto, 0, s, d) + payload


def _eth(payload, etype=0x0800, vlan=None):
    hdr = b"\x02" * 6 + b"\x04" * 6
    if vlan is not None:
        hdr += struct.pack("!HH", 0x8100, vlan)
    return hdr + struct.pack("!H", etype) + payload


def _icmp(itype, ident, seq):
    return struct.pack("!BBHHH", itype, 0, 0, ident, seq) + b"x" * 8


def _udp_tunnel(inner_frame):
    udp = struct.pack("!HHHH", 10065, 10064, 8 + len(inner_frame), 0)
    return _eth(_ip("127.0.0.1", "127.0.0.1", 17, udp + inner_frame))


def write_pcap(path, frames, tunnel=True, vlan=None):
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for t, frame in frames:
            if vlan is not None:
                frame = _eth(frame[14:], vlan=vlan)
            data = _udp_tunnel(frame) if tunnel else frame
            sec, usec = int(t), int(round((t - int(t)) * 1e6))
            f.write(struct.pack("<IIII", sec, usec, len(data), len(data)))
            f.write(data)


def ping_frames(n, lost, t0=1000.0, rtt=0.004, interval=1.0, ident=77):
    frames = []
    for s in range(1, n + 1):
        t = t0 + (s - 1) * interval
        frames.append((t, _eth(_ip("10.0.0.1", "10.0.0.2", 1,
                                   _icmp(8, ident, s)))))
        if s not in lost:
            frames.append((t + rtt, _eth(_ip("10.0.0.2", "10.0.0.1", 1,
                                             _icmp(0, ident, s)))))
    return frames


class PcapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_udp_tunnel_icmp_and_measured_outage(self):
        p = os.path.join(self.tmp, "x.pcap")
        write_pcap(p, ping_frames(20, lost={8, 9, 10}))
        log = pa.read_pcap_icmp(p)
        self.assertEqual(log.meta["pcap_istek"], "20")
        self.assertEqual(log.meta["pcap_yanit"], "17")
        res = pa.analyze(log, "baglanti_kopmasi")
        self.assertEqual(res["kayip_paket"], 3)
        self.assertAlmostEqual(res["rtt_medyan_ms"], 4.0, places=2)
        # seq 7 yanıtı (t=1006.004) -> seq 11 yanıtı (t=1010.004)
        self.assertAlmostEqual(res["kesinti_olculen_s"], 4.0, places=3)
        self.assertEqual(res["veri_kaynagi"], "pcap")

    def test_direct_ethernet_with_vlan(self):
        p = os.path.join(self.tmp, "v.pcap")
        write_pcap(p, ping_frames(5, lost=set()), tunnel=False, vlan=10)
        res = pa.analyze(pa.read_pcap_icmp(p), "normal")
        self.assertEqual(res["basarili_paket"], 5)

    def test_capture_without_icmp_is_rejected(self):
        p = os.path.join(self.tmp, "n.pcap")
        lldp = _eth(b"\x00" * 40, etype=0x88CC)
        write_pcap(p, [(1.0, lldp), (2.0, lldp)])
        with self.assertRaises(pa.MeasurementError) as cm:
            pa.read_pcap_icmp(p)
        self.assertIn("ölçüm yapılmadı", str(cm.exception))

    def test_pcapng_and_garbage_rejected(self):
        for name, blob in (("a.pcapng", b"\x0a\x0d\x0d\x0a" + b"\0" * 40),
                           ("b.pcap", b"not a pcap" * 5), ("c.pcap", b"")):
            p = os.path.join(self.tmp, name)
            with open(p, "wb") as f:
                f.write(blob)
            with self.assertRaises(pa.MeasurementError):
                pa.read_pcap_icmp(p)


# ----------------------------------------------------------------------
# Controller olayları (sentetik state.json)
# ----------------------------------------------------------------------
def fake_state(path, t0=1010.0):
    steps = lambda pairs: [{"step": s, "t": t0 + dt, "dt_ms": dt * 1000,  # noqa
                            "detail": ""} for s, dt in pairs]
    incs = [
        {"id": 1, "kind": "LINK_FAILURE", "link": "a:1<->b:2",
         "status": "NO_PATH", "steps": steps([("DETECTED", -500)])},
        {"id": 2, "kind": "LINK_FAILURE", "link": "a:1<->b:2",
         "status": "RESTORED",
         "steps": steps([("DETECTED", 0.0), ("CONFIRMED", 0.0001),
                         ("ROUTE_SELECTED", 0.0002),
                         ("FLOW_INSTALL_START", 0.0005),
                         ("PATH_ACTIVE", 0.0098), ("LINK_UP", 30.0),
                         ("FAILBACK_START", 40.0),
                         ("FAILBACK_COMPLETE", 40.012)])},
    ]
    with open(path, "w") as f:
        json.dump({"incidents": incs}, f)


class ControllerTimingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "s.json")
        fake_state(self.state)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_incident_timings(self):
        inc = pa.load_incidents(self.state)[1]
        tm = pa.incident_timings(inc)
        self.assertEqual(tm["tespit_path_active_ms"], 9.8)
        self.assertEqual(tm["tespit_flow_baslangic_ms"], 0.5)
        self.assertEqual(tm["linkup_failback_baslangic_ms"], 10000.0)
        self.assertEqual(tm["failback_islem_ms"], 12.0)

    def test_text_log_uses_latest_incident_with_note(self):
        log = pa.parse_ping_text(sample_text(failure_run(40)))
        res = pa.analyze(log, "baglanti_kopmasi",
                         pa.load_incidents(self.state))
        self.assertEqual(res["ctrl_olay_id"], 2)
        self.assertEqual(res["ctrl_tespit_path_active_ms"], 9.8)
        self.assertIn("zamanca eşleştirilemedi", res["notlar"])

    def test_pcap_window_and_first_reply_after_path_active(self):
        p = os.path.join(self.tmp, "x.pcap")
        # t0=1000: seq 8-10 kayıp; PATH_ACTIVE ~1010.0098; seq 11 yanıtı
        # 1010.004 (önce), seq 12 yanıtı 1011.004 -> ~994.2 ms sonra
        write_pcap(p, ping_frames(20, lost={8, 9, 10}))
        res = pa.analyze_files(None, p, self.state, "baglanti_kopmasi")
        self.assertEqual(res["ctrl_olay_id"], 2)
        self.assertAlmostEqual(res["path_active_ilk_yanit_ms"], 994.2,
                               places=1)

    def test_pcap_window_without_matching_incident(self):
        p = os.path.join(self.tmp, "y.pcap")
        write_pcap(p, ping_frames(10, lost={4}, t0=5000.0))
        res = pa.analyze_files(None, p, self.state, "baglanti_kopmasi")
        self.assertIsNone(res["ctrl_olay_id"])
        self.assertIn("zaman penceresinde", res["notlar"])


# ----------------------------------------------------------------------
# experiment_runner: dosyalar, CSV, grafik
# ----------------------------------------------------------------------
class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.raw = os.path.join(self.tmp, "ham")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, scenario, rep, text):
        os.makedirs(self.raw, exist_ok=True)
        with open(os.path.join(self.raw, "%s_t%d.txt" % (scenario, rep)),
                  "w", encoding="utf-8") as f:
            f.write(text)

    def test_new_template_does_not_overwrite(self):
        self.assertEqual(er.cmd_new(self.raw, "normal", 1, 100), 0)
        path = os.path.join(self.raw, "normal_t1.txt")
        with open(path, "a") as f:
            f.write(vpcs_reply(1, 3.0) + "\n")
        self.assertEqual(er.cmd_new(self.raw, "normal", 1, 100), 1)
        with open(path) as f:
            self.assertIn("icmp_seq=1", f.read())
        with open(path, encoding="utf-8") as f:
            log = pa.parse_ping_text(f.read())
        self.assertEqual(log.meta["senaryo"], "normal")
        self.assertEqual(log.expected, 100)

    def test_template_only_is_reported_as_no_data(self):
        er.cmd_new(self.raw, "failback", 2, 100)
        res = er.analyze_dir(self.raw)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["gonderilen_paket"], 0)
        self.assertEqual(res[0]["veri_turu"], "GERCEK_OLCUM")
        self.assertIn("henüz veri yok", res[0]["notlar"])
        written = er.write_outputs(res, self.out)
        self.assertEqual([os.path.basename(p) for p in written],
                         ["deney_sonuclari.csv"])     # grafik/özet yok

    def test_copy_state_does_not_overwrite(self):
        src = os.path.join(self.tmp, "state.json")
        fake_state(src)
        self.assertEqual(er.cmd_copy_state(self.raw, "failback", 1, src), 0)
        self.assertEqual(er.cmd_copy_state(self.raw, "failback", 1, src), 1)

    def test_csv_summary_and_charts(self):
        for rep in (1, 2, 3):
            self._write("normal", rep, sample_text(
                [vpcs_reply(s, 3.0 + rep) for s in range(1, 21)]))
            self._write("baglanti_kopmasi", rep, sample_text(
                failure_run(50, lost=range(20, 22 + rep))))
        results = er.analyze_dir(self.raw)
        self.assertEqual(len(results), 6)

        # Varsayılan: ÖRNEK veri özet ve grafiklere GİRMEZ
        written = er.write_outputs(results, self.out)
        self.assertEqual(len(written), 1)

        csv_path = os.path.join(self.out, "deney_sonuclari.csv")
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 6)
        self.assertEqual(list(rows[0].keys()), er.RESULT_COLUMNS)
        self.assertTrue(all(r["veri_turu"] == "ORNEK" for r in rows))
        kop = [r for r in rows if r["senaryo"] == "baglanti_kopmasi"]
        self.assertEqual(sorted(int(r["kayip_paket"]) for r in kop),
                         [3, 4, 5])
        self.assertTrue(all(r["durum"] == "BASARILI" for r in rows))

        # Testte açıkça izin verilince grafik "ÖRNEK VERİ" damgası taşır
        written = er.write_outputs(results, self.out, include_sample=True)
        names = sorted(os.path.basename(p) for p in written)
        self.assertIn("senaryo_ozeti.csv", names)
        self.assertIn("grafik_kayip_yuzde.svg", names)
        with open(os.path.join(self.out, "grafik_rtt_ort_ms.svg"),
                  encoding="utf-8") as f:
            svg = f.read()
        self.assertIn("ÖRNEK VERİ", svg)
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))

        with open(os.path.join(self.out, "senaryo_ozeti.csv"),
                  encoding="utf-8") as f:
            summ = {r["senaryo"]: r for r in csv.DictReader(f)}
        self.assertEqual(summ["normal"]["tekrar_sayisi"], "3")
        self.assertEqual(float(summ["normal"]["rtt_ort_ms_ort"]), 5.0)
        self.assertEqual(float(summ["baglanti_kopmasi"]
                               ["en_uzun_kayip_patlamasi_ort"]), 4.0)

    def test_bad_pcap_falls_back_to_text_with_note(self):
        self._write("baglanti_kopmasi", 1, sample_text(failure_run(40)))
        with open(os.path.join(self.raw, "baglanti_kopmasi_t1.pcap"),
                  "wb") as f:
            f.write(b"bozuk")
        res = er.analyze_dir(self.raw)[0]
        self.assertEqual(res["veri_kaynagi"], "vpcs_metin")
        self.assertEqual(res["kayip_paket"], 5)
        self.assertIn("pcap kullanılamadı", res["notlar"])


if __name__ == "__main__":
    unittest.main()
