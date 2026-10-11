"""
Aşama 6.5 - RecoveryAgent offline testi (GNS3/OS-Ken bağlantısı gerekmez).

Tüm agent zinciri (Monitoring -> Failure -> Routing -> Recovery) gerçek
TopologyManager ile çalıştırılır. Switchler sahte bir flow tablosu
(FakeFlowOps) ile temsil edilir; böylece kurulan/silinen her flow
doğrulanabilir. DPID ve port numaraları keyfidir.

Çalıştırma (proje kökünden):
    python3 -m unittest -v tests.test_recovery_agent_offline
"""

import logging
import unittest

from utils.event_bus import (EventBus, TOPO_LINK_ADDED, TOPO_LINK_REMOVED,
                             TOPO_SWITCH_REMOVED, PORT_HEALTH_CHANGED,
                             RECOVERY_REQUEST, HOST_SEEN, TIMER_TICK)
from agents import (MonitoringAgent, FailureDetectionAgent, RoutingAgent,
                    RecoveryAgent)
from agents.recovery_agent import (RECOVERY_FLOW_COOKIE,
                                   RECOVERY_FLOW_PRIORITY,
                                   FAILBACK_STABLE_SECONDS)
from topology.topology_manager import TopologyManager

LEARNED_COOKIE = 0x5D

# Keyfi DPID'ler
A, B, C, D = 0x9a3f00000000c1, 0x51, 0xdead0007, 0x3e8
# Keyfi port numaraları: {(u, v): (u'daki port, v'deki port)}
SQUARE = {(A, B): (17, 4), (A, C): (23, 9), (C, D): (11, 42),
          (D, B): (6, 31)}
H1, H2, H3 = "02:aa:00:00:00:01", "02:bb:00:00:00:02", "02:cc:00:00:00:03"
HOSTS = {H1: (A, 5), H2: (B, 12), H3: (C, 8)}


class FakeFlowOps(object):
    """Switch flow tablolarının sahte modeli.

    table: {dpid: {(priority, cookie, match_tuple): out_port}}
    match_tuple = (in_port, eth_src, eth_dst); None = wildcard."""

    def __init__(self):
        self.table = {}
        self.fail_on = None          # (dpid) -> add_flow False döner
        self.barriers = []
        self.adds = []

    def dpids(self):
        return sorted(self.table)

    def add_flow(self, dpid, priority, cookie, in_port, src, dst, out):
        if dpid not in self.table or dpid == self.fail_on or not cookie:
            return False
        self.table[dpid][(priority, cookie, (in_port, src, dst))] = out
        self.adds.append((dpid, in_port, src, dst, out))
        return True

    def delete_flow_strict(self, dpid, priority, cookie, in_port, src, dst):
        if dpid not in self.table or not cookie:
            return False
        self.table[dpid].pop((priority, cookie, (in_port, src, dst)), None)
        return True

    def delete_pair_flows(self, dpid, cookie, src, dst):
        if dpid not in self.table or not cookie:
            return False
        for k in [k for k in self.table[dpid]
                  if k[1] == cookie and k[2][1:] == (src, dst)]:
            del self.table[dpid][k]
        return True

    def barrier(self, dpid):
        self.barriers.append(dpid)
        return dpid in self.table

    def recovery_flows(self):
        return sorted((dpid, k[2][0], k[2][1], k[2][2], out)
                      for dpid, t in self.table.items()
                      for k, out in t.items()
                      if k[1] == RECOVERY_FLOW_COOKIE)


class Clock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class RecoveryTestBase(unittest.TestCase):

    def setUp(self):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.log = logging.getLogger("test")
        self.bus = EventBus()
        self.topo = TopologyManager(logger=self.log)
        self.ops = FakeFlowOps()
        self.clock = Clock()
        MonitoringAgent(self.bus, self.log)
        FailureDetectionAgent(self.bus, self.log)
        RoutingAgent(self.bus, self.topo, self.log)
        self.agent = RecoveryAgent(self.bus, self.log, topology=self.topo,
                                   flow_ops=self.ops,
                                   learned_cookie=LEARNED_COOKIE,
                                   clock=self.clock)
        self.requests = []
        self.bus.subscribe(RECOVERY_REQUEST, self.requests.append)

    # -- controller benzeri yardımcılar --------------------------------
    def build(self, ports, hosts=HOSTS):
        self.links = {}
        self.dpids = {}
        for (u, v), (pu, pv) in ports.items():
            self.dpids[u] = self.dpids[v] = object()
        for dpid in self.dpids:
            self.ops.table.setdefault(dpid, {
                # table-miss ve LLDP (cookie 0) + alakasız learned flow
                (0, 0, (None, None, None)): "CONTROLLER",
                (0xFFFF, 0, ("lldp", None, None)): "CONTROLLER",
                (1, LEARNED_COOKIE, (99, "02:ee:00:00:00:09",
                                     "02:ee:00:00:00:0a")): 98})
        self.topo.sync(self.dpids, {})
        for (u, v), (pu, pv) in ports.items():
            self.link_up(u, pu, v, pv)
        for mac, (dpid, port) in hosts.items():
            self.bus.publish(HOST_SEEN, {"mac": mac, "dpid": dpid,
                                         "port": port})
        self.ports = ports

    def _info(self, u, v):
        pu, pv = self.ports[(u, v)] if (u, v) in self.ports else \
            self.ports[(v, u)][::-1]
        return {"src_dpid": u, "src_port": pu, "dst_dpid": v, "dst_port": pv}

    def link_up(self, u, pu, v, pv):
        info = {"src_dpid": u, "src_port": pu, "dst_dpid": v, "dst_port": pv}
        self.links[(u, v)] = info
        self.topo.sync(self.dpids, self.links)
        self.bus.publish(TOPO_LINK_ADDED, dict(info))

    def link_down(self, u, v):
        info = self.links.pop((u, v))
        self.topo.sync(self.dpids, self.links)
        self.bus.publish(TOPO_LINK_REMOVED, dict(info))

    def restore(self, u, v):
        pu, pv = self.ports[(u, v)]
        self.link_up(u, pu, v, pv)

    def tick(self, advance):
        self.clock.t += advance
        self.bus.publish(TIMER_TICK, {"now": self.clock.t})

    def expected_flows(self, path, src, dst, hosts=HOSTS):
        """Graph portlarından bağımsız olarak beklenen flow listesi."""
        def port(u, v):
            if (u, v) in self.ports:
                return self.ports[(u, v)][0]
            return self.ports[(v, u)][1]
        flows = []
        for p, s, d in ((path, src, dst), (path[::-1], dst, src)):
            for i, dpid in enumerate(p):
                in_p = hosts[s][1] if i == 0 else port(dpid, p[i - 1])
                out_p = hosts[d][1] if i == len(p) - 1 else \
                    port(dpid, p[i + 1])
                flows.append((dpid, in_p, s, d, out_p))
        return sorted(flows)

    def non_recovery_entries(self):
        return {dpid: {k: v for k, v in t.items()
                       if k[1] != RECOVERY_FLOW_COOKIE}
                for dpid, t in self.ops.table.items()}


class RecoveryAgentOfflineTest(RecoveryTestBase):

    # A. geçerli alternatif yol: graph portları, çift yönlü plan
    def test_a_valid_alternative_path(self):
        self.build(SQUARE)
        self.link_down(A, B)
        self.assertEqual(self.requests[-1]["path"], [A, C, D, B])
        # H1(A)<->H2(B): A-B'yi kullanıyordu -> detour A-C-D-B.
        # H2(B)<->H3(C): eşit hop'lu B-A-C / B-D-C yollarından biri A-B'yi
        # kullanır -> etkilenmiş sayılır; B-[D-C-A]-C döngüsü çıkarılır.
        # H1(A)<->H3(C): doğrudan A-C, etkilenmedi -> flow yok.
        self.assertEqual(self.ops.recovery_flows(), sorted(
            self.expected_flows([A, C, D, B], H1, H2) +
            self.expected_flows([C, D, B], H3, H2)))
        self.assertFalse(any(H1 in f and H3 in f
                             for f in self.ops.recovery_flows()))
        for dpid, in_p, _, _, out_p in self.ops.recovery_flows():
            self.assertNotEqual(in_p, out_p)
        # Her yön hedeften kaynağa kuruldu: H1->H2 ilk flow B'de (hedef)
        first = [f for f in self.ops.adds if f[2] == H1][0]
        self.assertEqual(first[0], B)
        self.assertEqual(sorted(set(self.ops.barriers)), sorted([A, B, C, D]))

    # B. keyfi DPID / port numaraları
    def test_b_arbitrary_ids(self):
        a, b, c, d, e = 0x7fffffffffffffff, 0x2, 0x123456789, 0xabc, 0x77
        ports = {(a, b): (99, 98), (a, c): (77, 76), (c, d): (55, 54),
                 (d, b): (33, 32), (d, e): (14, 15)}
        hosts = {H1: (a, 44), H2: (b, 45), H3: (e, 46)}
        self.build(ports, hosts)
        self.link_down(a, b)
        # H1(a)<->H3(e): a-b-d-e eşit yollardan biri; a-c-d-b-d-e
        # döngüsü a-c-d-e'ye indirgenir. H2(b)<->H3(e): b-d-e, etkilenmedi.
        self.assertEqual(self.ops.recovery_flows(), sorted(
            self.expected_flows([a, c, d, b], H1, H2, hosts) +
            self.expected_flows([a, c, d, e], H1, H3, hosts)))
        self.assertFalse(any(H2 in f and H3 in f
                             for f in self.ops.recovery_flows()))

    # C. yetersiz host bağlamı: flow yok, SKIPPED
    def test_c_insufficient_host_context(self):
        self.build(SQUARE, hosts={})
        with self.assertLogs("test", "WARNING") as cm:
            self.link_down(A, B)
        self.assertEqual(self.ops.recovery_flows(), [])
        self.assertTrue(any("SKIPPED" in m and
                            "insufficient_forwarding_context" in m
                            for m in cm.output))

    def test_c2_host_on_isl_port_never_learned(self):
        self.build(SQUARE, hosts={})
        # H1 bir ISL portunda (A:17) görülürse host sayılmaz
        self.bus.publish(HOST_SEEN, {"mac": H1, "dpid": A, "port": 17})
        self.bus.publish(HOST_SEEN, {"mac": "01:00:5e:00:00:01",
                                     "dpid": A, "port": 5})
        self.assertEqual(self.agent._hosts, {})

    def test_c3_link_discovery_purges_wrong_host_location(self):
        self.build({(A, C): (23, 9)}, hosts={H1: (C, 9)})  # keşif öncesi
        self.assertNotIn(H1, self.agent._hosts)

    # D. alternatif yol yok: flow yok
    def test_d_no_alternative_path(self):
        self.build({(A, B): (17, 4)}, hosts={H1: (A, 5), H2: (B, 12)})
        self.link_down(A, B)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.ops.recovery_flows(), [])

    # E. cookie/priority izolasyonu
    def test_e_cookie_priority_isolation(self):
        self.build(SQUARE)
        before = self.non_recovery_entries()
        self.link_down(A, B)
        self.assertNotIn(RECOVERY_FLOW_COOKIE, (0, LEARNED_COOKIE))
        self.assertGreater(RECOVERY_FLOW_PRIORITY, 1)      # learned
        self.assertLess(RECOVERY_FLOW_PRIORITY, 0xFFFF)    # LLDP
        for dpid, t in self.ops.table.items():
            for (prio, cookie, match), _ in t.items():
                if cookie == RECOVERY_FLOW_COOKIE:
                    self.assertEqual(prio, RECOVERY_FLOW_PRIORITY)
                    self.assertNotIn(None, match)   # wildcard yok
        self.assertEqual(self.non_recovery_entries(), before)

    # F. DEGRADED: canlı topology değişmeden alternatif yol kurulur
    def test_f_degraded_request(self):
        self.build(SQUARE)
        edges = sorted(map(sorted, self.topo.graph.edges))
        self.bus.publish(PORT_HEALTH_CHANGED, {
            "dpid": A, "port_no": 17, "old_state": "HEALTHY",
            "new_state": "DEGRADED", "drop_ratio": 0.2, "error_ratio": 0.0})
        self.assertEqual(self.ops.recovery_flows(), sorted(
            self.expected_flows([A, C, D, B], H1, H2) +
            self.expected_flows([C, D, B], H3, H2)))
        # Hiçbir recovery flow'u DEGRADED A:17 / B:4 portuna çıkmıyor
        for dpid, _, _, _, out_p in self.ops.recovery_flows():
            self.assertNotIn((dpid, out_p), ((A, 17), (B, 4)))
        self.assertEqual(sorted(map(sorted, self.topo.graph.edges)), edges)
        self.assertTrue(self.topo.graph.has_edge(A, B))

    # G. tekrar eden istek: flowlar tekrar kurulmaz
    def test_g_duplicate_request(self):
        self.build(SQUARE)
        self.link_down(A, B)
        n = len(self.ops.adds)
        self.bus.publish(RECOVERY_REQUEST, dict(self.requests[-1]))
        self.bus.publish(RECOVERY_REQUEST, dict(self.requests[-1]))
        self.assertEqual(len(self.ops.adds), n)
        self.assertEqual(len(self.agent._sessions), 1)

    # H. LINK_UP -> FAILBACK_PENDING, flow hemen silinmez
    def test_h_link_up_starts_pending(self):
        self.build(SQUARE)
        self.link_down(A, B)
        flows = self.ops.recovery_flows()
        with self.assertLogs("test", "INFO") as cm:
            self.restore(A, B)
        self.assertTrue(any("FAILBACK_PENDING" in m for m in cm.output))
        self.assertEqual(self.ops.recovery_flows(), flows)
        self.tick(FAILBACK_STABLE_SECONDS - 1)
        self.assertEqual(self.ops.recovery_flows(), flows)

    # I. kararlı failback: yalnızca recovery flowları silinir
    def test_i_stable_failback(self):
        self.build(SQUARE)
        # Etkilenen çift için eski bir learned flow ve alakasız learned flow
        self.ops.table[A][(1, LEARNED_COOKIE, (5, H1, H2))] = 17
        self.link_down(A, B)
        self.restore(A, B)
        before = self.non_recovery_entries()
        with self.assertLogs("test", "INFO") as cm:
            self.tick(FAILBACK_STABLE_SECONDS + 1)
        text = "\n".join(cm.output)
        for word in ("FAILBACK_START", "RECOVERY_FLOWS_REMOVED",
                     "FAILBACK_COMPLETE"):
            self.assertIn(word, text)
        self.assertEqual(self.ops.recovery_flows(), [])
        self.assertEqual(self.agent._sessions, {})
        # Yalnızca H1<->H2 learned flow'u silindi; table-miss, LLDP ve
        # alakasız learned flow duruyor
        after = self.non_recovery_entries()
        self.assertNotIn((1, LEARNED_COOKIE, (5, H1, H2)), after[A])
        before[A].pop((1, LEARNED_COOKIE, (5, H1, H2)))
        self.assertEqual(after, before)
        self.assertTrue(self.topo.graph.has_edge(A, B))   # normal yol var

    # J. kararlı süre dolmadan link tekrar düşer -> failback iptal
    def test_j_failback_cancelled(self):
        self.build(SQUARE)
        self.link_down(A, B)
        flows = self.ops.recovery_flows()
        self.restore(A, B)
        self.tick(5)
        with self.assertLogs("test", "INFO") as cm:
            self.link_down(A, B)
        self.assertTrue(any("FAILBACK_CANCELLED" in m for m in cm.output))
        self.tick(FAILBACK_STABLE_SECONDS * 3)
        self.assertEqual(self.ops.recovery_flows(), flows)
        self.assertEqual(len(self.agent._sessions), 1)

    # K. switch kaldırma temizliği
    def test_k_switch_removed(self):
        self.build(SQUARE)
        self.link_down(A, B)
        self.assertEqual(len(self.agent._sessions), 1)
        del self.dpids[D]
        self.topo.sync(self.dpids, self.links)
        self.bus.publish(TOPO_SWITCH_REMOVED, {"dpid": D})
        self.ops.table.pop(D)
        self.assertEqual(self.agent._sessions, {})
        self.assertEqual(self.agent._pair_owner, {})
        self.assertEqual(self.ops.recovery_flows(), [])

    # Ek: kısmi kurulum başarı sayılmaz, geri alınır
    def test_partial_install_rolled_back(self):
        self.build(SQUARE)
        self.ops.fail_on = C
        with self.assertLogs("test", "ERROR") as cm:
            self.link_down(A, B)
        self.assertTrue(any("FLOW_INSTALL_FAILED" in m for m in cm.output))
        self.assertEqual(self.ops.recovery_flows(), [])
        self.assertEqual(self.agent._sessions, {})

    # Ek: DEGRADED -> HEALTHY failback; DEGRADED -> FAILED failback DEĞİL
    def test_degraded_failback_and_failed_upgrade(self):
        self.build(SQUARE)
        ev = {"dpid": A, "port_no": 17, "drop_ratio": 0.2,
              "error_ratio": 0.0}
        self.bus.publish(PORT_HEALTH_CHANGED, dict(
            ev, old_state="HEALTHY", new_state="DEGRADED"))
        flows = self.ops.recovery_flows()
        self.assertTrue(flows)
        # Link tamamen düşer (FailureAgent DEGRADED -> FAILED bildirir)
        self.bus.publish(PORT_HEALTH_CHANGED, dict(
            ev, old_state="DEGRADED", new_state="FAILED"))
        self.link_down(A, B)
        self.tick(FAILBACK_STABLE_SECONDS * 3)
        self.assertEqual(self.ops.recovery_flows(), flows)
        session = list(self.agent._sessions.values())[0]
        self.assertEqual(session["trigger"], "LINK_FAILURE")
        # Link geri gelir -> kararlı süre sonrası failback
        self.restore(A, B)
        self.tick(FAILBACK_STABLE_SECONDS + 1)
        self.assertEqual(self.ops.recovery_flows(), [])

    # Ek: recovery yolundaki bir link de düşerse ve yol yoksa oturum
    # geçersizleşir (karadelik bırakılmaz)
    def test_recovery_path_link_down_invalidates(self):
        self.build(SQUARE)
        self.link_down(A, B)
        self.link_down(C, D)          # A-B ve C-D yok: H1-H2 kopuk
        self.assertEqual(self.ops.recovery_flows(), [])
        self.assertEqual(self.agent._sessions, {})

    # Ek: canlı graph RecoveryAgent tarafından değiştirilmez
    def test_live_graph_not_mutated(self):
        self.build(SQUARE)
        self.link_down(A, B)
        self.assertFalse(self.topo.graph.has_edge(A, B))
        self.assertEqual(self.topo.edge_count(), 3)


if __name__ == "__main__":
    unittest.main()
