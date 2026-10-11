"""
Aşama 6.4 - RoutingAgent offline testi (GNS3/OS-Ken gerekmez).

Gerçek TopologyManager kullanılır; switch/link verisi controller'ın
sync() formatında sentetik olarak verilir. DPID'ler ve portlar bilinçli
olarak rastgele/keyfi seçilmiştir (sabit DPID yok).

Çalıştırma (proje kökünden):
    python3 -m unittest -v tests.test_routing_agent_offline
"""

import logging
import unittest

from utils.event_bus import (EventBus, LINK_FAILURE, RECOVERY_REQUEST,
                             PORT_HEALTH_CHANGED, TOPO_SWITCH_REMOVED)
from agents.routing_agent import RoutingAgent
from topology.topology_manager import TopologyManager

# Keyfi DPID'ler (gerçek GNS3 DPID'lerine benzemeyen)
A, B, C, D = 0x9a3f00000000c1, 0x51, 0xdead0007, 0x3e8
# Keyfi port numaraları
PORTS = {(A, B): (17, 4), (A, C): (23, 9), (C, D): (11, 42), (D, B): (6, 31)}
HOST_PORT_A = 1


class RoutingAgentOfflineTest(unittest.TestCase):

    def setUp(self):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        log = logging.getLogger("test")
        self.bus = EventBus()
        self.topo = TopologyManager(logger=log)
        self.agent = RoutingAgent(self.bus, self.topo, log)
        self.requests = []
        self.bus.subscribe(RECOVERY_REQUEST, self.requests.append)

    def build(self, pairs, ports=PORTS):
        """pairs: [(u, v), ...] -> controller formatında sync()."""
        links = {}
        dpids = {}
        for u, v in pairs:
            pu, pv = ports[(u, v)]
            links[(u, v)] = {"src_dpid": u, "src_port": pu,
                             "dst_dpid": v, "dst_port": pv}
            dpids[u] = dpids[v] = object()
        self.links = links
        self.topo.sync(dpids, links)
        self.dpids = dpids

    def fail_link(self, u, v):
        """Controller sırası: önce graph güncellenir, sonra LINK_FAILURE."""
        info = self.links.pop((u, v))
        self.topo.sync(self.dpids, self.links)
        self.bus.publish(LINK_FAILURE, dict(info))

    def health(self, dpid, port, old, new):
        self.bus.publish(PORT_HEALTH_CHANGED, {
            "dpid": dpid, "port_no": port, "old_state": old,
            "new_state": new, "reason": "test", "drop_ratio": 0.2,
            "error_ratio": 0.0, "consecutive": 2})

    def square(self):
        self.build([(A, B), (A, C), (C, D), (D, B)])

    # A. arızalı link, alternatif yol var
    def test_a_link_failure_with_alternative(self):
        self.square()
        self.fail_link(A, B)
        self.assertEqual(len(self.requests), 1)
        r = self.requests[0]
        self.assertEqual(r["path"], [A, C, D, B])
        self.assertEqual(r["hop_count"], 3)
        self.assertEqual(r["trigger"], "LINK_FAILURE")
        self.assertEqual(r["reason"], "link_down")
        # RecoveryAgent'ın eski alanları korunuyor
        for key in ("failed_link", "src_dpid", "dst_dpid", "path"):
            self.assertIn(key, r)
        self.assertEqual((r["src_dpid"], r["dst_dpid"]), (A, B))

    # B. arızalı link, alternatif yok
    def test_b_link_failure_no_alternative(self):
        self.build([(A, B)])
        with self.assertLogs("test", "WARNING") as cm:
            self.fail_link(A, B)
        self.assertEqual(self.requests, [])
        self.assertTrue(any("NO_ALTERNATIVE_PATH" in m for m in cm.output))

    # C. DEGRADED switch-switch linki: graph'ta durur ama hesapta hariç
    def test_c_degraded_inter_switch_link(self):
        self.square()
        edges_before = sorted(map(sorted, self.topo.graph.edges))
        port_on_a = PORTS[(A, B)][0]
        self.health(A, port_on_a, "HEALTHY", "DEGRADED")
        self.assertEqual(len(self.requests), 1)
        r = self.requests[0]
        self.assertEqual(r["trigger"], "PORT_DEGRADED")
        self.assertEqual(r["reason"], "metrics")
        self.assertEqual(r["path"], [A, C, D, B])
        self.assertNotIn((A, B), list(zip(r["path"], r["path"][1:])))
        # Canlı graph değişmedi
        self.assertTrue(self.topo.graph.has_edge(A, B))
        self.assertEqual(sorted(map(sorted, self.topo.graph.edges)),
                         edges_before)
        self.assertEqual(self.topo.edge_count(), 4)

    def test_c2_degraded_from_other_end_and_no_alternative(self):
        self.build([(A, B)])
        with self.assertLogs("test", "WARNING") as cm:
            self.health(B, PORTS[(A, B)][1], "HEALTHY", "DEGRADED")
        self.assertEqual(self.requests, [])
        self.assertTrue(any("NO_ALTERNATIVE_PATH" in m for m in cm.output))
        self.assertTrue(self.topo.graph.has_edge(A, B))

    # D. DEGRADED host portu: reroute yok
    def test_d_degraded_host_port_ignored(self):
        self.square()
        with self.assertLogs("test", "INFO") as cm:
            self.health(A, HOST_PORT_A, "HEALTHY", "DEGRADED")
        self.assertEqual(self.requests, [])
        self.assertTrue(any("DEGRADED_HOST_PORT" in m for m in cm.output))

    # E. tekrar eden DEGRADED eventleri spam üretmez
    def test_e_duplicate_degraded(self):
        self.square()
        pa, pb = PORTS[(A, B)]
        self.health(A, pa, "HEALTHY", "DEGRADED")
        self.health(A, pa, "HEALTHY", "DEGRADED")   # aynı event tekrar
        self.health(B, pb, "HEALTHY", "DEGRADED")   # linkin diğer ucu
        self.assertEqual(len(self.requests), 1)

    # F. DEGRADED -> HEALTHY: yalnızca log, failback / istek yok
    def test_f_degraded_to_healthy(self):
        self.square()
        pa = PORTS[(A, B)][0]
        self.health(A, pa, "HEALTHY", "DEGRADED")
        self.assertEqual(len(self.requests), 1)
        with self.assertLogs("test", "INFO") as cm:
            self.health(A, pa, "DEGRADED", "HEALTHY")
        self.assertTrue(any("DEGRADED_CONDITION_CLEARED" in m
                            for m in cm.output))
        self.assertEqual(len(self.requests), 1)    # failback isteği yok
        self.assertEqual(self.agent._degraded, {})
        # Temizlendikten sonra yeni bir DEGRADED tekrar karar üretir
        self.health(A, pa, "HEALTHY", "DEGRADED")
        self.assertEqual(len(self.requests), 2)

    # Diğer DEGRADED linkler LINK_FAILURE kararında tercihen kaçınılır
    def test_failure_avoids_other_degraded_with_fallback(self):
        self.square()
        self.health(C, PORTS[(C, D)][0], "HEALTHY", "DEGRADED")
        self.requests.clear()
        self.fail_link(A, B)
        # Tek alternatif yol DEGRADED C-D'den geçiyor -> yine de seçilir
        self.assertEqual(self.requests[0]["path"], [A, C, D, B])
        self.assertEqual(self.requests[0]["excluded_edges"], [])

    # Eşit hop'lu yollarda deterministik seçim
    def test_equal_cost_deterministic(self):
        # A-B arızası; A-C-B ve A-D-B eşit (2 hop)
        ports = dict(PORTS)
        ports.update({(A, D): (2, 3), (C, B): (5, 6)})
        self.build([(A, B), (A, C), (C, B), (A, D), (D, B)], ports)
        self.fail_link(A, B)
        self.assertEqual(self.requests[0]["path"],
                         min([A, C, B], [A, D, B]))

    # G. dinamik ID'ler: farklı keyfi DPID'lerle aynı davranış
    def test_g_dynamic_ids(self):
        ids = [0x7fffffffffffffff, 0x2, 0x123456789, 0xabc]
        a, b, c, d = ids
        ports = {(a, b): (99, 98), (a, c): (77, 76), (c, d): (55, 54),
                 (d, b): (33, 32)}
        self.build(list(ports), ports)
        self.health(b, 98, "HEALTHY", "DEGRADED")
        # DEGRADED portu b üzerinde bildirildi -> yön b -> a
        self.assertEqual(self.requests[-1]["path"], [b, d, c, a])
        self.assertTrue(self.topo.graph.has_edge(a, b))

    def test_switch_removed_clears_degraded(self):
        self.square()
        self.health(A, PORTS[(A, B)][0], "HEALTHY", "DEGRADED")
        self.bus.publish(TOPO_SWITCH_REMOVED, {"dpid": B})
        self.assertEqual(self.agent._degraded, {})


if __name__ == "__main__":
    unittest.main()
