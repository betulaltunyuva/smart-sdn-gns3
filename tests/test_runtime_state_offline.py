"""
Aşama 7 - RuntimeStateWriter (dashboard state çıktısı) offline testi.

GNS3/OS-Ken gerekmez. Gerçek agent zinciri + TopologyManager, controller
benzeri sahte bir obje üzerinden çalıştırılır. Doğrulananlar:
  - Writer eklenmesi agent davranışını DEĞİŞTİRMEZ (aynı RECOVERY_REQUEST,
    aynı flow tablosu, aynı log satırları).
  - state.json geçerli JSON'dur; failure -> routing -> recovery -> failback
    zinciri, linkler, metrikler ve olaylar state'e yansır.
  - Yazma atomiktir: hata durumunda eski dosya bozulmaz, geçici dosya kalmaz.

Çalıştırma (proje kökünden):
    python3 -m unittest -v tests.test_runtime_state_offline
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from utils.event_bus import (EventBus, TOPO_LINK_ADDED, TOPO_LINK_REMOVED,
                             PORT_STATUS_UPDATE, PORT_STATS_UPDATE,
                             RECOVERY_REQUEST, HOST_SEEN, TIMER_TICK)
from agents import (MonitoringAgent, FailureDetectionAgent, RoutingAgent,
                    RecoveryAgent)
from agents.recovery_agent import FAILBACK_STABLE_SECONDS
from topology.topology_manager import TopologyManager
from utils.runtime_state import RuntimeStateWriter, link_id
from tests.test_recovery_agent_offline import (FakeFlowOps, Clock, SQUARE,
                                               HOSTS, LEARNED_COOKIE, A, B, C,
                                               D)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "dashboard"))
import state_reader  # noqa: E402


class ListHandler(logging.Handler):
    def __init__(self):
        super(ListHandler, self).__init__(level=logging.INFO)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class FakeDatapath(object):
    def __init__(self, dpid):
        self.id = dpid
        self.address = ("192.168.122.%d" % (10 + dpid % 200), 40000 + dpid % 999)


class FakeController(object):
    """SDNController'ın writer'ın okuduğu alanlarının minimum kopyası."""
    STATS_INTERVAL = 5

    def __init__(self, name, with_writer, state_path=None):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.handlers = []
        self.capture = ListHandler()
        self.logger.addHandler(self.capture)
        self.datapaths, self.links = {}, {}
        self.isl_ports, self.tree_ports, self.mac_to_port = {}, {}, {}
        self.topology = TopologyManager(logger=self.logger)
        self.event_bus = EventBus(logger=self.logger)
        self.ops = FakeFlowOps()
        self.clock = Clock()
        # Controller ile aynı sıra: agentlar, sonra writer
        self.monitoring_agent = MonitoringAgent(self.event_bus, self.logger)
        self.failure_agent = FailureDetectionAgent(self.event_bus,
                                                   self.logger)
        self.routing_agent = RoutingAgent(self.event_bus, self.topology,
                                          self.logger)
        self.recovery_agent = RecoveryAgent(
            self.event_bus, self.logger, topology=self.topology,
            flow_ops=self.ops, learned_cookie=LEARNED_COOKIE,
            clock=self.clock)
        self.requests = []
        self.state_writer = None
        if with_writer:
            self.state_writer = RuntimeStateWriter(self, path=state_path)
        self.event_bus.subscribe(RECOVERY_REQUEST, self.requests.append)

    # -- controller benzeri olaylar ------------------------------------
    def build(self):
        for (u, v) in SQUARE:
            for d in (u, v):
                self.datapaths.setdefault(d, FakeDatapath(d))
                self.ops.table.setdefault(d, {})
        self.topology.sync(self.datapaths, {})
        for (u, v), (pu, pv) in SQUARE.items():
            self.link_up(u, pu, v, pv)
        for mac, (dpid, port) in HOSTS.items():
            self.event_bus.publish(HOST_SEEN, {"mac": mac, "dpid": dpid,
                                               "port": port})

    def link_up(self, u, pu, v, pv):
        info = {"src_dpid": u, "src_port": pu, "dst_dpid": v, "dst_port": pv}
        self.links[(u, v)] = info
        # SDNController.link_add_handler ile aynı log satırı
        self.logger.info("LINK_ADDED src_dpid=%016x src_port=%s "
                         "dst_dpid=%016x dst_port=%s "
                         "toplam aktif link sayısı=%d",
                         u, pu, v, pv, len(self.links))
        for d, p in ((u, pu), (v, pv)):
            self.isl_ports.setdefault(d, set()).add(p)
        self.topology.sync(self.datapaths, self.links)
        self.event_bus.publish(TOPO_LINK_ADDED, dict(info))

    def link_down(self, u, v):
        info = self.links.pop((u, v))
        self.topology.sync(self.datapaths, self.links)
        self.event_bus.publish(TOPO_LINK_REMOVED, dict(info))

    def tick(self, advance):
        self.clock.t += advance
        self.event_bus.publish(TIMER_TICK, {"now": self.clock.t})

    def port_stats(self, dpid, t, packets):
        self.event_bus.publish(PORT_STATUS_UPDATE, {"dpid": dpid, "ports": [
            {"port_no": 5, "name": "eth5", "link_up": True,
             "admin_up": True}]})
        self.event_bus.publish(PORT_STATS_UPDATE, {
            "dpid": dpid, "timestamp": t, "ports": [{
                "port_no": 5, "rx_bytes": packets * 100,
                "tx_bytes": packets * 50, "rx_packets": packets,
                "tx_packets": packets // 2, "rx_errors": 0, "tx_errors": 0,
                "rx_dropped": packets // 10, "tx_dropped": 0,
                "duration_sec": t, "duration_nsec": 0}]})


def scenario(ctl):
    ctl.build()
    ctl.link_down(A, B)
    pu, pv = SQUARE[(A, B)]
    ctl.link_up(A, pu, B, pv)
    ctl.tick(1)
    ctl.tick(FAILBACK_STABLE_SECONDS + 1)


class RuntimeStateOfflineTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdn_state_test_")
        self.path = os.path.join(self.tmp, "runtime", "state.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self):
        with open(self.path) as f:
            return f.read()

    def read(self):
        return json.loads(self.raw())

    # A. Writer agent davranışını değiştirmez
    def test_a_writer_does_not_change_agent_behaviour(self):
        plain = FakeController("plain", with_writer=False)
        observed = FakeController("observed", with_writer=True,
                                  state_path=self.path)
        for ctl in (plain, observed):
            scenario(ctl)
        self.assertEqual(plain.requests, observed.requests)
        self.assertEqual(plain.ops.table, observed.ops.table)
        self.assertEqual(plain.ops.adds, observed.ops.adds)
        self.assertEqual(plain.capture.messages, observed.capture.messages)
        self.assertTrue(plain.requests)          # zincir gerçekten çalıştı

    # B. Failure -> routing -> recovery -> failback state'e yansır
    def test_b_incident_chain_in_state(self):
        ctl = FakeController("chain", True, self.path)
        ctl.build()
        ctl.state_writer.write()
        s = self.read()
        self.assertEqual(len(s["switches"]), 4)
        self.assertEqual(len(s["links"]), 4)
        self.assertEqual(s["failed_links"], [])
        self.assertEqual(s["recovery"]["status"], "IDLE")

        ctl.link_down(A, B)
        ctl.state_writer.write()
        s = self.read()
        lid = link_id(A, SQUARE[(A, B)][0], B, SQUARE[(A, B)][1])
        self.assertEqual([l["id"] for l in s["failed_links"]], [lid])
        self.assertEqual(len(s["links"]), 3)
        inc = s["latest_failure"]
        self.assertEqual(inc["link"], lid)
        self.assertEqual(inc["status"], "RECOVERED")
        self.assertIsNotNone(inc["recovery_ms"])
        self.assertEqual([st["step"] for st in inc["steps"]],
                         ["DETECTED", "CONFIRMED", "ROUTE_SELECTED",
                          "FLOW_INSTALL_START", "PATH_ACTIVE"])
        self.assertEqual(inc["route"]["path"],
                         ["%016x" % d for d in (A, C, D, B)])
        self.assertEqual(s["latest_route"]["hop_count"], 3)
        self.assertEqual(s["recovery"]["status"], "ACTIVE")
        sess = s["recovery"]["sessions"][0]
        self.assertEqual(sess["link"], lid)
        self.assertGreater(sess["flow_count"], 0)
        self.assertEqual(s["agents"]["recovery"]["active_sessions"], 1)
        self.assertEqual(s["agents"]["failure"]["failed"], 0)  # metrik yok
        sources = set(e["source"] for e in s["events"])
        self.assertTrue({"MONITORING", "FAILURE", "ROUTING",
                         "RECOVERY"} <= sources)

        pu, pv = SQUARE[(A, B)]
        ctl.link_up(A, pu, B, pv)
        ctl.tick(1)
        ctl.state_writer.write()
        s = self.read()
        self.assertEqual(s["failed_links"], [])
        self.assertEqual(s["recovery"]["status"], "FAILBACK_PENDING")
        self.assertEqual(s["latest_failure"]["status"], "FAILBACK_PENDING")

        ctl.tick(FAILBACK_STABLE_SECONDS + 1)
        ctl.state_writer.write()
        s = self.read()
        self.assertEqual(s["recovery"]["status"], "IDLE")
        self.assertEqual(s["latest_failure"]["status"], "RESTORED")
        self.assertIn("FAILBACK_COMPLETE",
                      [st["step"] for st in s["latest_failure"]["steps"]])

    # C. Host trafiği bilinmezse recovery SKIPPED olarak görünür
    def test_c_skipped_recovery_reason(self):
        ctl = FakeController("skip", True, self.path)
        for (u, v) in SQUARE:
            for d in (u, v):
                ctl.datapaths.setdefault(d, FakeDatapath(d))
        ctl.topology.sync(ctl.datapaths, {})
        for (u, v), (pu, pv) in SQUARE.items():
            ctl.link_up(u, pu, v, pv)
        ctl.link_down(C, D)
        ctl.state_writer.write()
        inc = self.read()["latest_failure"]
        self.assertEqual(inc["status"], "SKIPPED")
        self.assertEqual(inc["outcome_reason"],
                         "insufficient_forwarding_context")

    # D. Metrikler ve geçmiş
    def test_d_metrics(self):
        ctl = FakeController("metrics", True, self.path)
        ctl.build()
        ctl.port_stats(A, 100, 1000)
        ctl.port_stats(A, 105, 2000)
        ctl.port_stats(A, 110, 2600)
        ctl.state_writer.write()
        s = self.read()
        ports = [p for p in s["metrics"]["ports"]
                 if p["dpid"] == "%016x" % A and p["port_no"] == 5]
        self.assertEqual(len(ports), 1)
        p = ports[0]
        self.assertAlmostEqual(p["packet_rate"], (600 + 300) / 5.0)
        self.assertEqual(p["drop_delta"], 60)
        self.assertEqual(len(s["metrics"]["history"]["%016x:5" % A]), 2)
        self.assertEqual(s["agents"]["monitoring"]["status"], "RUNNING")

    # E. Atomik yazma: hata eski dosyayı bozmaz, geçici dosya kalmaz
    def test_e_atomic_write(self):
        ctl = FakeController("atomic", True, self.path)
        ctl.build()
        ctl.state_writer.write()
        before = self.raw()

        def boom():
            raise RuntimeError("snapshot failed")
        ctl.state_writer.snapshot = boom
        with self.assertRaises(RuntimeError):
            ctl.state_writer.write()
        self.assertEqual(self.raw(), before)

        # Geçici dosya yazıldıktan sonra, os.replace sırasında hata
        del ctl.state_writer.snapshot
        with mock.patch("utils.runtime_state.os.replace",
                        side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ctl.state_writer.write()
        self.assertEqual(self.raw(), before)
        leftovers = [f for f in os.listdir(os.path.dirname(self.path))
                     if f != "state.json"]
        self.assertEqual(leftovers, [])

    # F. Dashboard okuyucusu eksik / bozuk dosyada çökmez
    def test_f_state_reader(self):
        state, err, age = state_reader.load_state(self.path)
        self.assertIsNone(state)
        self.assertIn("yok", err)
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write('{"timestamp": 1, "contr')
        state, err, age = state_reader.load_state(self.path)
        self.assertIsNone(state)
        self.assertIn("JSON", err)
        ctl = FakeController("reader", True, self.path)
        ctl.build()
        ctl.state_writer.write()
        state, err, age = state_reader.load_state(self.path)
        self.assertIsNone(err)
        self.assertLess(age, 5)
        status, _ = state_reader.controller_status(state, age)
        self.assertEqual(status, "ONLINE")      # yazan process = bu test
        names = state_reader.name_map(state, [])
        self.assertEqual(names["%016x" % B], "dp-51")


if __name__ == "__main__":
    unittest.main()
