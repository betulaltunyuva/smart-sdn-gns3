"""
Aşama 9.2/9.3 - Veri seti toplayıcı ve etiketleme offline testi
(GNS3/OS-Ken gerekmez).

Çalıştırma (proje kökünden):
    python3 -m unittest -v tests.test_dataset_collector_offline
"""

import csv
import datetime
import logging
import os
import shutil
import tempfile
import unittest

from utils.event_bus import (EventBus, PORT_METRICS, PORT_STATS_UPDATE,
                             PORT_STATUS_UPDATE, LINK_UP, LINK_DOWN)
from agents.monitoring_agent import MonitoringAgent
from utils.dataset_collector import (DatasetCollector, COLUMNS,
                                     enabled_from_env)
from utils import dataset_labels as dl

UTC = datetime.timezone.utc


class FakeClock(object):
    def __init__(self):
        self.now = datetime.datetime(2026, 11, 23, 10, 0, 0, tzinfo=UTC)
        self.mono = 100.0

    def __call__(self):
        return self.now

    def advance(self, sec):
        self.now += datetime.timedelta(seconds=sec)
        self.mono += sec


def metrics(dpid=1, port=2, **over):
    m = {"dpid": dpid, "port_no": port, "name": "eth%d" % port,
         "link_up": True, "admin_up": True, "interval_sec": 5.0,
         "rx_bytes": 1000, "tx_bytes": 2000, "rx_packets": 10,
         "tx_packets": 20, "rx_errors": 0, "tx_errors": 0,
         "rx_dropped": 0, "tx_dropped": 0,
         "rx_bytes_per_sec": 200.0, "tx_bytes_per_sec": 400.0,
         "rx_mbps": 0.0016, "tx_mbps": 0.0032, "throughput_mbps": 0.0048,
         "rx_pps": 2.0, "tx_pps": 4.0, "packet_rate": 6.0}
    m.update(over)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "sub", "port_metrics.csv")
        self.bus = EventBus(logger=logging.getLogger("t"))
        self.clock = FakeClock()
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, **kw):
        kw.setdefault("experiment_id", "exp1")
        c = DatasetCollector(self.bus, path=self.path, clock=self.clock,
                             monotonic=lambda: self.clock.mono, **kw)
        self.addCleanup(c.close)
        return c

    def rows(self, path=None):
        with open(path or self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


class CollectorTests(Base):
    def test_port_metrics_recorded(self):
        self.make()
        self.bus.publish(PORT_METRICS, metrics())
        r = self.rows()[0]
        self.assertEqual(r["dpid"], "1")
        self.assertEqual(r["dpid_hex"], "0000000000000001")
        self.assertEqual(r["port_no"], "2")
        self.assertEqual(r["port_name"], "eth2")
        self.assertEqual(r["rx_bytes"], "1000")
        self.assertEqual(r["tx_packets"], "20")
        self.assertEqual(float(r["throughput_mbps"]), 0.0048)
        self.assertEqual(float(r["packet_rate_pps"]), 6.0)
        self.assertEqual(r["link_up"], "1")
        self.assertEqual(r["admin_up"], "1")
        self.assertEqual(r["experiment_id"], "exp1")

    def test_header_and_append_across_instances(self):
        c = self.make()
        self.bus.publish(PORT_METRICS, metrics())
        c.close()
        self.make()
        self.clock.advance(5)
        self.bus.publish(PORT_METRICS, metrics(rx_bytes=5000))
        with open(self.path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0].split(","), list(COLUMNS))
        self.assertEqual(len(lines), 3)        # tek başlık, iki veri satırı
        self.assertEqual(sum(l.startswith("timestamp_utc") for l in lines), 1)

    def test_mismatched_header_never_modifies_old_file(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("a,b\n1,2\n")
        c = self.make()
        self.bus.publish(PORT_METRICS, metrics())
        with open(self.path) as f:
            self.assertEqual(f.read(), "a,b\n1,2\n")
        self.assertNotEqual(c.path, self.path)
        self.assertEqual(len(self.rows(c.path)), 1)

    def test_missing_counters_left_blank_not_zero(self):
        self.make()
        m = metrics(rx_bytes=None, tx_errors=0xffffffffffffffff,
                    rx_mbps=None, throughput_mbps=float("nan"),
                    link_up=None, name=None, interval_sec=-1,
                    rx_dropped=-5, tx_dropped="x")
        self.bus.publish(PORT_METRICS, m)
        r = self.rows()[0]
        for col in ("rx_bytes", "tx_errors", "rx_mbps", "throughput_mbps",
                    "link_up", "port_name", "interval_sec", "rx_dropped",
                    "tx_dropped"):
            self.assertEqual(r[col], "", col)
        self.assertEqual(r["tx_bytes"], "2000")
        self.assertEqual(r["rx_errors"], "0")      # gerçek 0 korunur

    def test_unmeasured_fields_always_blank(self):
        self.make()
        self.bus.publish(PORT_METRICS, metrics(latency_ms=12.0,
                                               e2e_loss_percent=3.0))
        r = self.rows()[0]
        self.assertEqual(r["latency_ms"], "")
        self.assertEqual(r["e2e_loss_percent"], "")
        self.assertEqual(r["declared_load_mbps"], "")

    def test_declared_load_recorded_only_when_given(self):
        self.make(declared_load_mbps=10)
        self.bus.publish(PORT_METRICS, metrics())
        self.assertEqual(float(self.rows()[0]["declared_load_mbps"]), 10.0)

    def test_invalid_payload_skipped_safely(self):
        c = self.make()
        for bad in ({}, {"dpid": 1}, {"dpid": "x", "port_no": 1},
                    {"dpid": True, "port_no": 1}, metrics(port=-1)):
            self.bus.publish(PORT_METRICS, bad)
        self.assertEqual(c.rows_skipped_invalid, 5)
        self.assertEqual(self.rows(), [])
        self.bus.publish(PORT_METRICS, metrics())    # hâlâ çalışıyor
        self.assertEqual(len(self.rows()), 1)

    def test_timestamp_is_utc_iso(self):
        self.make()
        self.bus.publish(PORT_METRICS, metrics())
        ts = self.rows()[0]["timestamp_utc"]
        self.assertEqual(ts, "2026-11-23T10:00:00.000Z")
        self.assertEqual(dl.parse_utc(ts), self.clock.now)

    def test_duplicate_delivery_dropped_but_idle_polls_kept(self):
        c = self.make()
        self.bus.publish(PORT_METRICS, metrics())
        self.bus.publish(PORT_METRICS, metrics())    # aynı anda tekrar
        self.assertEqual(c.rows_skipped_duplicate, 1)
        self.clock.advance(5)                        # gerçek sonraki poll
        self.bus.publish(PORT_METRICS, metrics())    # içerik aynı (boşta)
        self.assertEqual(len(self.rows()), 2)
        # farklı port kopya sayılmaz
        self.bus.publish(PORT_METRICS, metrics(port=3))
        self.assertEqual(len(self.rows()), 3)

    def test_isl_port_from_link_events(self):
        self.make()
        self.bus.publish(PORT_METRICS, metrics())
        self.assertEqual(self.rows()[0]["isl_port"], "")     # bilinmiyor
        link = {"src_dpid": 1, "src_port": 2, "dst_dpid": 3, "dst_port": 1}
        self.bus.publish(LINK_UP, link)
        self.clock.advance(5)
        self.bus.publish(PORT_METRICS, metrics())
        self.bus.publish(LINK_DOWN, link)
        self.clock.advance(5)
        self.bus.publish(PORT_METRICS, metrics())
        self.assertEqual([r["isl_port"] for r in self.rows()],
                         ["", "1", "0"])

    def test_default_label_unknown_and_invalid_label_falls_back(self):
        self.make()
        self.bus.publish(PORT_METRICS, metrics())
        r = self.rows()[0]
        self.assertEqual((r["label"], r["label_source"]), ("UNKNOWN", "none"))
        c2 = DatasetCollector(self.bus, path=self.path + "2",
                              label="bogus", clock=self.clock)
        self.addCleanup(c2.close)
        self.assertEqual(c2.label, "UNKNOWN")

    def test_operator_label_is_recorded_as_such(self):
        self.make(label="normal")
        self.bus.publish(PORT_METRICS, metrics())
        r = self.rows()[0]
        self.assertEqual((r["label"], r["label_source"]),
                         ("NORMAL", "operator_env"))

    def test_zero_traffic_does_not_become_failure(self):
        self.make()
        self.bus.publish(PORT_METRICS, metrics(
            rx_bytes_per_sec=0.0, tx_bytes_per_sec=0.0, rx_mbps=0.0,
            tx_mbps=0.0, throughput_mbps=0.0, rx_pps=0.0, tx_pps=0.0,
            packet_rate=0.0, link_up=False))
        self.assertEqual(self.rows()[0]["label"], "UNKNOWN")

    def test_rotation(self):
        c = self.make()
        c.max_bytes = os.path.getsize(self.path) + 10   # 1 satır sığar
        self.bus.publish(PORT_METRICS, metrics())
        self.clock.advance(5)
        self.bus.publish(PORT_METRICS, metrics(port=4))
        rotated = [f for f in os.listdir(os.path.dirname(self.path))
                   if f != "port_metrics.csv"]
        self.assertEqual(len(rotated), 1)
        self.assertEqual(len(self.rows()), 1)

    def test_write_failure_does_not_raise_and_disables(self):
        c = self.make()
        c._file.close()               # yazmayı bozar (ValueError)
        for i in range(8):
            self.clock.advance(5)
            self.bus.publish(PORT_METRICS, metrics(rx_bytes=i))
        self.assertTrue(c.write_errors >= 1)

    def test_unwritable_path_disables_without_exception(self):
        blocker = os.path.join(self.tmp, "file")
        open(blocker, "w").close()
        c = DatasetCollector(self.bus, path=os.path.join(blocker, "x.csv"),
                             clock=self.clock)
        self.assertTrue(c.disabled)
        self.bus.publish(PORT_METRICS, metrics())    # hata yok

    def test_disabled_by_default_from_env(self):
        self.assertFalse(enabled_from_env({}))
        self.assertIsNone(DatasetCollector.from_env(self.bus, environ={}))
        self.assertIsNone(DatasetCollector.from_env(
            self.bus, environ={"SDN_DATASET": "0"}))
        c = DatasetCollector.from_env(self.bus, environ={
            "SDN_DATASET": "1", "SDN_DATASET_PATH": self.path,
            "SDN_DATASET_EXPERIMENT": "e9", "SDN_DATASET_LABEL": "LOAD",
            "SDN_DATASET_LOAD_MBPS": "5"})
        self.addCleanup(c.close)
        self.assertEqual((c.experiment_id, c.label), ("e9", "LOAD"))

    def test_end_to_end_with_real_monitoring_agent(self):
        """Gerçek MonitoringAgent çıktısı (geriye uyumluluk) CSV'ye yazılır."""
        MonitoringAgent(self.bus, logging.getLogger("t"))
        self.make()
        self.bus.publish(PORT_STATUS_UPDATE, {"dpid": 5, "ports": [
            {"port_no": 1, "name": "eth1", "link_up": True,
             "admin_up": True}]})

        def stats(t, rx):
            return {"dpid": 5, "timestamp": t, "ports": [{
                "port_no": 1, "rx_bytes": rx, "tx_bytes": 0, "rx_packets": 1,
                "tx_packets": 0, "rx_errors": 0, "tx_errors": 0,
                "rx_dropped": 0, "tx_dropped": 0}]}
        self.bus.publish(PORT_STATS_UPDATE, stats(0.0, 0))
        self.assertEqual(self.rows(), [])            # baseline: satır yok
        self.clock.advance(5)
        self.bus.publish(PORT_STATS_UPDATE, stats(5.0, 625000))
        r = self.rows()[0]
        self.assertEqual(r["port_name"], "eth1")
        self.assertAlmostEqual(float(r["rx_mbps"]), 1.0, places=3)
        self.assertEqual(r["tx_mbps"], "0.000000")
        self.assertEqual(r["interval_sec"], "5.000")


class LabelTests(Base):
    def ann(self, **over):
        a = {"experiment_id": "exp1", "start_utc": "2026-11-23T10:00:00Z",
             "end_utc": "2026-11-23T10:10:00Z", "label": "NORMAL",
             "evidence_type": "baseline_no_fault",
             "evidence_note": "yük/arıza yok"}
        a.update(over)
        return a

    def test_evidence_rules(self):
        dl.validate_annotation(self.ann())
        for bad in (
                self.ann(label="FAILURE", evidence_type="zero_traffic"),
                self.ann(label="FAILURE", evidence_type="lldp_loss"),
                self.ann(label="CONGESTION", evidence_type="traffic_generator"),
                self.ann(label="LOAD", evidence_type="drop_counters"),
                self.ann(label="UNKNOWN"),
                self.ann(label="BOGUS"),
                self.ann(evidence_note=""),
                self.ann(experiment_id=""),
                self.ann(start_utc="2026-11-23T10:00:00"),   # tz yok
                self.ann(end_utc="2026-11-23T09:00:00Z")):
            with self.assertRaises(ValueError, msg=str(bad)):
                dl.validate_annotation(bad)
        dl.validate_annotation(self.ann(label="FAILURE",
                                        evidence_type="physical_link_down"))

    def _write_annotations(self, rows):
        p = os.path.join(self.tmp, "ann.csv")
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=dl.ANNOTATION_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return p

    def _raw(self, n=4):
        self.make()
        for i in range(n):
            self.bus.publish(PORT_METRICS, metrics(rx_bytes=i))
            self.clock.advance(300)          # 5 dk aralık: 10:00,10:05,...
        return self.path

    def test_apply_annotations_labels_only_verified_interval(self):
        raw = self._raw(4)                   # 10:00 10:05 10:10 10:15
        with open(raw, "rb") as f:
            before = f.read()
        ann = self._write_annotations([self.ann()])  # [10:00, 10:10)
        out = os.path.join(self.tmp, "out.csv")
        stats = dl.apply_annotations(raw, ann, out)
        self.assertEqual([r["label"] for r in self.rows(out)],
                         ["NORMAL", "NORMAL", "UNKNOWN", "UNKNOWN"])
        self.assertEqual(self.rows(out)[0]["label_source"],
                         "annotation:baseline_no_fault")
        self.assertEqual((stats["labeled"], stats["unknown"]), (2, 2))
        with open(raw, "rb") as f:
            self.assertEqual(f.read(), before)             # ham değişmedi

    def test_other_experiment_and_conflicts_stay_unknown(self):
        raw = self._raw(2)
        ann = self._write_annotations([
            self.ann(experiment_id="baska"),
            self.ann(label="LOAD", evidence_type="traffic_generator",
                     start_utc="2026-11-23T10:00:00Z",
                     end_utc="2026-11-23T10:01:00Z"),
            self.ann(start_utc="2026-11-23T10:00:00Z",
                     end_utc="2026-11-23T10:01:00Z")])
        out = os.path.join(self.tmp, "out.csv")
        stats = dl.apply_annotations(raw, ann, out)
        self.assertEqual([r["label"] for r in self.rows(out)],
                         ["UNKNOWN", "UNKNOWN"])
        self.assertEqual(stats["conflict"], 1)

    def test_refuses_overwrite_and_invalid_annotation_file(self):
        raw = self._raw(1)
        ann = self._write_annotations([self.ann()])
        with self.assertRaises(ValueError):
            dl.apply_annotations(raw, ann, raw)
        out = os.path.join(self.tmp, "out.csv")
        open(out, "w").close()
        with self.assertRaises(ValueError):
            dl.apply_annotations(raw, ann, out)
        bad = self._write_annotations([self.ann(label="FAILURE",
                                                evidence_type="zero_traffic")])
        with self.assertRaises(ValueError):
            dl.apply_annotations(raw, bad, os.path.join(self.tmp, "o2.csv"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "o2.csv")))


if __name__ == "__main__":
    unittest.main()
