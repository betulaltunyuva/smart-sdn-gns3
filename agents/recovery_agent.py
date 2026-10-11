"""
Smart SDN (GNS3) - Aşama 6 / 6.5: Recovery Agent (OpenFlow self-healing)

RoutingAgent'ın RECOVERY_REQUEST'ini DOĞRULAR ve seçilen alternatif yolu
OpenFlow 1.3 flowları ile UYGULAR. Rota kararı vermez; yalnızca aldığı yolu
(src_dpid -> dst_dpid detour'u) etkilenen host trafiğine uygular.

Güvenlik kuralları:
  - Wildcard / "her şey -> port X" flow'u KURULMAZ. Her recovery flow'u
    in_port + eth_src + eth_dst (iki bilinen unicast host MAC'i) eşler.
  - Yalnızca bilinen host konumları (HOST_SEEN) ile çalışır; bağlam yoksa
    "[RECOVERY] SKIPPED reason=insufficient_forwarding_context" loglanır.
  - Kısmi kurulum başarı sayılmaz: bir flow gönderilemezse bu istekte
    kurulanlar geri alınır (FLOW_INSTALL_FAILED).
  - Silme işlemleri yalnızca RECOVERY_FLOW_COOKIE (ve failback'te etkilenen
    MAC çifti için learned cookie) ile yapılır; table-miss ve LLDP
    (cookie=0) flowlarına asla dokunulmaz.
  - Canlı topology graph'ı DEĞİŞTİRİLMEZ (yalnızca okunur / kopyalanır).

Etkilenen trafik: bilinen her host çifti (farklı switchlerde) için mevcut
yol; çift zaten bir recovery oturumundaysa o oturumun yolu, değilse olay
öncesi graph'taki (LINK_FAILURE: canlı graph + arızalı edge kopyası)
en az hop'lu yollar kullanılır. Learning switch hangi eşit maliyetli yolu
kullandığını saklamadığından, etkilenen edge eşit-hop'lu yollardan
HERHANGİ birindeyse çift etkilenmiş sayılır. Yeni yol = mevcut yolun
etkilenen edge'e kadarki kısmı + RoutingAgent detour'u + kalan kısım
(döngüler çıkarılır).

Failback: LINK_UP (LINK_FAILURE oturumu) veya DEGRADED -> HEALTHY
(PORT_DEGRADED oturumu) sonrası FAILBACK_PENDING; FAILBACK_STABLE_SECONDS
boyunca link canlı graph'ta kalırsa yalnızca bu oturumun flowları silinir
ve normal learning forwarding devralır. Zamanlayıcı ayrı thread değildir:
controller'ın 5 sn'lik döngüsündeki TIMER_TICK eventi kullanılır.
"""

import logging
import time

try:
    import networkx as nx
except ImportError:
    nx = None

from utils.event_bus import (RECOVERY_REQUEST, LINK_FAILURE, LINK_UP,
                             PORT_HEALTH_CHANGED, TOPO_LINK_ADDED,
                             TOPO_SWITCH_REMOVED, HOST_SEEN, TIMER_TICK)

# ----------------------------------------------------------------------
# Recovery flow parametreleri
# ----------------------------------------------------------------------
# Mevcut cookie'ler: table-miss=0, LLDP (os_ken.topology)=0,
# learned=0x5D. Recovery flowları bunlardan ayrı bir cookie kullanır.
RECOVERY_FLOW_COOKIE = 0x6E
# Learned flowlar priority=1, table-miss=0, LLDP=0xFFFF. Recovery flowları
# learned flowları ezer, LLDP'yi asla ezmez.
RECOVERY_FLOW_PRIORITY = 100
# Link geri geldikten sonra failback için gereken kararlı süre (saniye).
# TIMER_TICK 5 sn'de bir geldiğinden fiili bekleme 10-15 sn'dir.
FAILBACK_STABLE_SECONDS = 10

TRIGGER_LINK_FAILURE = "LINK_FAILURE"
TRIGGER_PORT_DEGRADED = "PORT_DEGRADED"
_TRIGGERS = (TRIGGER_LINK_FAILURE, TRIGGER_PORT_DEGRADED)


def _link_key(link):
    """Yönsüz link anahtarı: frozenset({(dpid, port), (dpid, port)})."""
    return frozenset(((link["src_dpid"], link["src_port"]),
                      (link["dst_dpid"], link["dst_port"])))


def _is_unicast_mac(mac):
    try:
        return not (int(mac.split(":")[0], 16) & 1)
    except (AttributeError, ValueError):
        return False


class RecoveryAgent(object):

    def __init__(self, event_bus, logger=None, topology=None, flow_ops=None,
                 learned_cookie=None, clock=time.monotonic):
        """topology : controller'ın TopologyManager örneği (salt okunur)
        flow_ops : controller'ın verdiği minimum OpenFlow yeteneği
                   (add_flow / delete_flow_strict / delete_pair_flows /
                   barrier / dpids). None ise agent yalnızca loglar.
        learned_cookie: failback'te etkilenen MAC çiftinin eski learned
                   flowlarını silmek için (None ise silinmez)."""
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        self.topology = topology
        self.flow_ops = flow_ops
        self.learned_cookie = learned_cookie
        self.clock = clock
        # Host konumları: {mac: (dpid, port)} (yalnızca host portlarından)
        self._hosts = {}
        # Bugüne kadar switch-switch linki olarak görülmüş portlar; bu
        # portlarda host öğrenilmez (link düşse bile).
        self._isl_ports = set()
        # Aktif oturumlar: {link_key: session}
        #   session = {"trigger", "reason", "link_key", "affected_link",
        #              "routing_path", "started", "failback_at",
        #              "degraded_ports": set((dpid, port)),
        #              "pairs": {frozenset({mac_a, mac_b}):
        #                        {"path": [dpid...] (sıralı ilk MAC'ten),
        #                         "flows": [(dpid, in_port, src, dst,
        #                                    out_port), ...]}}}
        self._sessions = {}
        # Host çifti -> sahibi olan oturumun link_key'i (çift başına tek
        # aktif recovery yolu)
        self._pair_owner = {}

        self.bus.subscribe(RECOVERY_REQUEST, self.on_recovery_request)
        self.bus.subscribe(LINK_FAILURE, self.on_link_failure)
        self.bus.subscribe(LINK_UP, self.on_link_up)
        self.bus.subscribe(PORT_HEALTH_CHANGED, self.on_port_health_changed)
        self.bus.subscribe(TOPO_LINK_ADDED, self.on_topo_link_added)
        self.bus.subscribe(TOPO_SWITCH_REMOVED, self.on_switch_removed)
        self.bus.subscribe(HOST_SEEN, self.on_host_seen)
        self.bus.subscribe(TIMER_TICK, self.on_tick)

    # ------------------------------------------------------------------
    # Host konum kaydı
    # ------------------------------------------------------------------
    def on_host_seen(self, ev):
        """ev: {"mac", "dpid", "port"}. Controller yalnızca host tarafı
        (mevcut ISL olmayan, veri) portlarından gelen unicast kaynak
        MAC'leri bildirir; burada ayrıca geçmiş ISL portları da elenir."""
        mac, loc = ev["mac"], (ev["dpid"], ev["port"])
        if not _is_unicast_mac(mac) or loc in self._isl_ports:
            return
        old = self._hosts.get(mac)
        if old == loc:
            return
        self._hosts[mac] = loc
        self.logger.info("[RECOVERY] HOST_LOCATION mac=%s dpid=%016x "
                         "port=%s", mac, loc[0], loc[1])
        if old is not None:
            # Host taşındı: bu host'u içeren recovery flowları artık yanlış
            for key in set(k for pair, k in self._pair_owner.items()
                           if mac in pair):
                self._close_session(key, "SESSION_INVALIDATED",
                                    "host_moved mac=%s" % mac)

    def on_topo_link_added(self, link):
        """Yeni ISL portlarını işaretle; bu portlarda (keşif öncesi) yanlış
        öğrenilmiş host kayıtlarını sil."""
        ends = set(_link_key(link))
        self._isl_ports |= ends
        for mac in [m for m, loc in self._hosts.items() if loc in ends]:
            del self._hosts[mac]

    # ------------------------------------------------------------------
    # RECOVERY_REQUEST -> doğrulama -> plan -> kurulum
    # ------------------------------------------------------------------
    def on_recovery_request(self, req):
        trigger = req.get("trigger", TRIGGER_LINK_FAILURE)
        path = list(req.get("path") or [])
        link = req.get("affected_link") or req.get("failed_link")
        self.logger.info("[RECOVERY] REQUEST trigger=%s reason=%s "
                         "src_dpid=%s dst_dpid=%s path=[%s]",
                         trigger, req.get("reason"),
                         self._fmt(req.get("src_dpid")),
                         self._fmt(req.get("dst_dpid")),
                         ", ".join(self._fmt(d) for d in path))

        if self.flow_ops is None or self.topology is None or nx is None:
            self._skip(trigger, "execution_disabled")
            return
        problem = self._validate_request(trigger, path, link, req)
        if problem:
            self._skip(trigger, "invalid_request", problem)
            return

        key = _link_key(link)
        session = self._sessions.get(key)
        if session is not None:
            # Aynı link için zaten aktif recovery var: flowlar tekrar
            # kurulmaz. Failback bekliyorsa iptal edilir.
            self._cancel_failback(session, "link_unhealthy_again")
            if trigger == TRIGGER_LINK_FAILURE:
                self._mark_link_failed(session)
            self.logger.info("[RECOVERY] DUPLICATE_REQUEST ignored "
                             "trigger=%s link=%s (session already active)",
                             trigger, self._fmt_link(key))
            return

        plan, skipped = self._plan(trigger, key, path)
        for pair, why in skipped:
            self.logger.info("[RECOVERY] SKIPPED pair=%s reason=%s",
                             self._fmt_pair(pair), why)
        if not plan:
            if len(self._hosts_by_switch()) < 2:
                self._skip(trigger, "insufficient_forwarding_context",
                           "known_hosts=%d" % len(self._hosts))
            elif not skipped:
                self._skip(trigger, "no_affected_host_traffic",
                           "link=%s" % self._fmt_link(key))
            else:
                self._skip(trigger, "insufficient_forwarding_context",
                           "link=%s" % self._fmt_link(key))
            return

        session = {"trigger": trigger, "reason": req.get("reason"),
                   "link_key": key, "affected_link": dict(link),
                   "routing_path": path, "started": self.clock(),
                   "failback_at": None, "degraded_ports": set(),
                   "pairs": plan}
        if trigger == TRIGGER_PORT_DEGRADED and req.get("degraded_port"):
            dp = req["degraded_port"]
            session["degraded_ports"].add((dp["dpid"], dp["port_no"]))

        if not self._install(session):
            return
        self._take_over_pairs(session)
        self._sessions[key] = session
        for pair, entry in sorted(plan.items(), key=lambda i: sorted(i[0])):
            self.logger.info("[RECOVERY] PATH_ACTIVE trigger=%s link=%s "
                             "pair=%s path=[%s] flows=%d",
                             trigger, self._fmt_link(key),
                             self._fmt_pair(pair),
                             ", ".join(self._fmt(d) for d in entry["path"]),
                             len(entry["flows"]))

    def _validate_request(self, trigger, path, link, req):
        """Sorun varsa açıklama, yoksa None döner."""
        graph = self.topology.graph
        if trigger not in _TRIGGERS:
            return "unknown_trigger"
        if link is None or any(link.get(k) is None for k in
                               ("src_dpid", "src_port",
                                "dst_dpid", "dst_port")):
            return "missing_affected_link"
        if len(path) < 2 or len(set(path)) != len(path):
            return "bad_path"
        if (path[0], path[-1]) != (req.get("src_dpid"), req.get("dst_dpid")):
            return "path_endpoints_mismatch"
        ends = set((link["src_dpid"], link["dst_dpid"]))
        if set((path[0], path[-1])) != ends:
            return "path_not_for_affected_link"
        key = _link_key(link)
        for a, b in zip(path, path[1:]):
            if not graph.has_edge(a, b):
                return "edge_not_in_topology=%s-%s" % (self._fmt(a),
                                                       self._fmt(b))
            if self._edge_is(a, b, key):
                return "path_uses_affected_link"
        return None

    # ------------------------------------------------------------------
    # Planlama: etkilenen host çiftleri ve port bazlı flow listesi
    # ------------------------------------------------------------------
    def _hosts_by_switch(self):
        """Graph'ta bulunan switchlere bağlı bilinen hostlar."""
        graph = self.topology.graph
        result = {}
        for mac, (dpid, port) in self._hosts.items():
            if graph.has_node(dpid) and (dpid, port) not in self._isl_ports:
                result.setdefault(dpid, []).append(mac)
        return result

    def _plan(self, trigger, key, detour):
        """{pair: {"path", "flows"}} planı ve [(pair, neden)] atlananlar."""
        graph = self.topology.graph
        (a, pa), (b, pb) = sorted(key)
        # Olay öncesi graph: LINK_FAILURE'da arızalı edge graph'tan zaten
        # çıkarıldı; KOPYA üzerine geri eklenir (canlı graph değişmez).
        before = graph
        if (trigger == TRIGGER_LINK_FAILURE and not graph.has_edge(a, b)
                and graph.has_node(a) and graph.has_node(b)):
            before = nx.Graph(graph)
            before.add_edge(a, b, ports={a: pa, b: pb})

        macs = sorted(m for ms in self._hosts_by_switch().values()
                      for m in ms)
        plan, skipped = {}, []
        for i, src in enumerate(macs):
            for dst in macs[i + 1:]:
                s_loc, d_loc = self._hosts[src], self._hosts[dst]
                if s_loc[0] == d_loc[0]:
                    continue          # aynı switch: ISL kullanmaz
                pair = frozenset((src, dst))
                current = self._current_paths(pair, s_loc[0], d_loc[0],
                                              before, key)
                affected = [p for p in current if self._uses(p, key)]
                if not affected:
                    continue
                new_path = self._stitch(min(affected), key, detour)
                problem = self._check_path(new_path, key)
                if problem is None:
                    flows = (self._direction_flows(new_path, src, dst) +
                             self._direction_flows(new_path[::-1], dst, src))
                    problem = self._check_flows(flows)
                if problem:
                    skipped.append((pair, problem))
                    continue
                plan[pair] = {"path": new_path, "flows": flows}
        return plan, skipped

    def _current_paths(self, pair, s_dpid, d_dpid, before, key):
        """Çiftin şu an kullanıyor olabileceği yollar (src -> dst yönünde)."""
        owner = self._pair_owner.get(pair)
        if owner is not None:
            path = self._sessions[owner]["pairs"][pair]["path"]
            return [path if path[0] == s_dpid else path[::-1]]
        try:
            return list(nx.all_shortest_paths(before, s_dpid, d_dpid))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def _stitch(self, path, key, detour):
        """path'teki etkilenen edge'i RoutingAgent detour'u ile değiştirir
        ve oluşan döngüleri çıkarır."""
        for i in range(len(path) - 1):
            if self._edge_is(path[i], path[i + 1], key):
                seg = detour if detour[0] == path[i] else detour[::-1]
                joined = path[:i] + list(seg) + path[i + 2:]
                break
        simple = []
        for node in joined:
            if node in simple:
                simple = simple[:simple.index(node) + 1]
            else:
                simple.append(node)
        return simple

    def _check_path(self, path, key):
        graph = self.topology.graph
        for a, b in zip(path, path[1:]):
            if not graph.has_edge(a, b):
                return "stitched_edge_not_in_topology"
            if self._edge_is(a, b, key):
                return "stitched_path_uses_affected_link"
        return None

    def _direction_flows(self, path, src, dst):
        """src -> dst yönü için flow listesi, HEDEFTEN KAYNAĞA sıralı."""
        graph = self.topology.graph
        flows = []
        for i, dpid in enumerate(path):
            if i == 0:
                in_port = self._hosts[src][1]
            else:
                in_port = graph.edges[path[i - 1], dpid]["ports"][dpid]
            if i == len(path) - 1:
                out_port = self._hosts[dst][1]
            else:
                out_port = graph.edges[dpid, path[i + 1]]["ports"][dpid]
            flows.append((dpid, in_port, src, dst, out_port))
        flows.reverse()
        return flows

    def _check_flows(self, flows):
        for dpid, in_port, src, dst, out_port in flows:
            if in_port == out_port:
                return "in_port_equals_out_port dpid=%s" % self._fmt(dpid)
            if in_port is None or out_port is None:
                return "unknown_port dpid=%s" % self._fmt(dpid)
        return None

    # ------------------------------------------------------------------
    # Kurulum / silme
    # ------------------------------------------------------------------
    def _install(self, session):
        flows = [f for pair in sorted(session["pairs"], key=sorted)
                 for f in session["pairs"][pair]["flows"]]
        self.logger.info("[RECOVERY] FLOW_INSTALL_START trigger=%s link=%s "
                         "pairs=%d flows=%d", session["trigger"],
                         self._fmt_link(session["link_key"]),
                         len(session["pairs"]), len(flows))
        installed = []
        for flow in flows:
            dpid, in_port, src, dst, out_port = flow
            ok = self.flow_ops.add_flow(dpid, RECOVERY_FLOW_PRIORITY,
                                        RECOVERY_FLOW_COOKIE, in_port,
                                        src, dst, out_port)
            if not ok:
                self.logger.error("[RECOVERY] FLOW_INSTALL_FAILED "
                                  "dpid=%016x in_port=%s out_port=%s "
                                  "src=%s dst=%s installed=%d/%d "
                                  "(rolling back)", dpid, in_port,
                                  out_port, src, dst, len(installed),
                                  len(flows))
                # Rollback: başka aktif oturuma ait match'ler silinmez
                owned = set(self._flow_match(f)
                            for other in self._sessions.values()
                            for e in other["pairs"].values()
                            for f in e["flows"])
                self._remove_flows([f for f in installed
                                    if self._flow_match(f) not in owned])
                return False
            installed.append(flow)
            self.logger.info("[RECOVERY] FLOW_INSTALLED dpid=%016x "
                             "in_port=%s out_port=%s src=%s dst=%s",
                             dpid, in_port, out_port, src, dst)
        for dpid in sorted(set(f[0] for f in flows)):
            self.flow_ops.barrier(dpid)
        return True

    def _remove_flows(self, flows):
        """Yalnızca verilen recovery flowlarını (strict) siler."""
        removed = 0
        for dpid, in_port, src, dst, _ in flows:
            if self.flow_ops.delete_flow_strict(dpid, RECOVERY_FLOW_PRIORITY,
                                                RECOVERY_FLOW_COOKIE,
                                                in_port, src, dst):
                removed += 1
        return removed

    @staticmethod
    def _flow_match(flow):
        return flow[:4]

    def _take_over_pairs(self, session):
        """Başka oturuma ait çiftleri yeni oturuma devreder; eski oturumun
        artık kullanılmayan flowlarını siler (aynı match ADD ile zaten
        güncellendi). Boşalan oturum kapatılır."""
        key = session["link_key"]
        for pair, entry in session["pairs"].items():
            old_key = self._pair_owner.get(pair)
            self._pair_owner[pair] = key
            if old_key is None or old_key == key:
                continue
            old = self._sessions[old_key]
            new_matches = set(self._flow_match(f) for f in entry["flows"])
            stale = [f for f in old["pairs"].pop(pair)["flows"]
                     if self._flow_match(f) not in new_matches]
            self._remove_flows(stale)
            if not old["pairs"]:
                del self._sessions[old_key]
                self.logger.info("[RECOVERY] SESSION_SUPERSEDED link=%s "
                                 "by=%s", self._fmt_link(old_key),
                                 self._fmt_link(key))

    def _close_session(self, key, event, reason):
        session = self._sessions.pop(key)
        flows = []
        for pair, entry in session["pairs"].items():
            flows.extend(entry["flows"])
            if self._pair_owner.get(pair) == key:
                del self._pair_owner[pair]
        removed = self._remove_flows(flows)
        self.logger.info("[RECOVERY] RECOVERY_FLOWS_REMOVED link=%s "
                         "removed=%d/%d", self._fmt_link(key), removed,
                         len(flows))
        if event:
            self.logger.warning("[RECOVERY] %s link=%s reason=%s",
                                event, self._fmt_link(key), reason)
        return session

    # ------------------------------------------------------------------
    # Failback ve oturum geçerliliği
    # ------------------------------------------------------------------
    def on_link_failure(self, link):
        key = _link_key(link)
        session = self._sessions.get(key)
        if session is not None:
            self._cancel_failback(session, "link_down_again")
            self._mark_link_failed(session)
        # Recovery yolu artık düşen bir linki kullanıyorsa oturum geçersiz:
        # flowları silinir, normal learning forwarding devralır.
        for other_key, s in list(self._sessions.items()):
            if any(self._uses(e["path"], key) for e in s["pairs"].values()):
                self._close_session(other_key, "SESSION_INVALIDATED",
                                    "recovery_path_link_down")

    @staticmethod
    def _mark_link_failed(session):
        """DEGRADED oturumunun linki tamamen düştü: failback artık
        DEGRADED -> HEALTHY ile değil LINK_UP ile başlar."""
        session["trigger"] = TRIGGER_LINK_FAILURE
        session["reason"] = "link_down"
        session["degraded_ports"].clear()

    def on_link_up(self, link):
        session = self._sessions.get(_link_key(link))
        if session is not None and session["trigger"] == TRIGGER_LINK_FAILURE:
            self._start_failback(session)

    def on_port_health_changed(self, ev):
        port = (ev["dpid"], ev["port_no"])
        for session in self._sessions.values():
            if (session["trigger"] != TRIGGER_PORT_DEGRADED
                    or port not in session["link_key"]):
                continue
            if ev.get("new_state") == "DEGRADED":
                session["degraded_ports"].add(port)
                self._cancel_failback(session, "port_degraded_again")
            elif (ev.get("old_state") == "DEGRADED"
                  and ev.get("new_state") == "HEALTHY"):
                session["degraded_ports"].discard(port)
                if not session["degraded_ports"]:
                    self._start_failback(session)

    def _start_failback(self, session):
        if session["failback_at"] is not None:
            return
        session["failback_at"] = self.clock() + FAILBACK_STABLE_SECONDS
        self.logger.info("[RECOVERY] FAILBACK_PENDING link=%s trigger=%s "
                         "stable_seconds=%d", self._fmt_link(
                             session["link_key"]),
                         session["trigger"], FAILBACK_STABLE_SECONDS)

    def _cancel_failback(self, session, reason):
        if session["failback_at"] is None:
            return
        session["failback_at"] = None
        self.logger.warning("[RECOVERY] FAILBACK_CANCELLED link=%s reason=%s "
                            "(recovery path stays active)",
                            self._fmt_link(session["link_key"]), reason)

    def on_tick(self, ev=None):
        now = self.clock()
        for key, session in list(self._sessions.items()):
            if session["failback_at"] is None or now < session["failback_at"]:
                continue
            problem = self._failback_problem(session)
            if problem == "link_not_in_topology":
                self._cancel_failback(session, problem)
            elif problem is None:
                self._failback(key)
            # diğer durumlarda bekleme sürer, sonraki TICK'te tekrar bakılır

    def _failback_problem(self, session):
        graph = self.topology.graph
        (a, pa), (b, pb) = sorted(session["link_key"])
        if not (graph.has_edge(a, b) and
                graph.edges[a, b]["ports"] == {a: pa, b: pb}):
            return "link_not_in_topology"
        if session["degraded_ports"]:
            return "port_still_degraded"
        # Normal (learning) forwarding için bilinen hostlar arasında canlı
        # graph'ta yol olmalı
        for pair in session["pairs"]:
            locs = [self._hosts.get(m) for m in pair]
            if None in locs:
                continue
            s, d = locs[0][0], locs[1][0]
            if not (graph.has_node(s) and graph.has_node(d)
                    and nx.has_path(graph, s, d)):
                return "no_normal_path"
        return None

    def _failback(self, key):
        session = self._sessions[key]
        self.logger.info("[RECOVERY] FAILBACK_START link=%s trigger=%s "
                         "pairs=%d", self._fmt_link(key),
                         session["trigger"], len(session["pairs"]))
        self._close_session(key, None, None)
        # Etkilenen çiftlerin olası eski learned flowları (yalnızca learned
        # cookie + bu MAC çifti) silinir; sonraki paketler yeni topolojide
        # yeniden öğrenilir.
        if self.learned_cookie:
            for pair in session["pairs"]:
                a, b = sorted(pair)
                for dpid in self.flow_ops.dpids():
                    self.flow_ops.delete_pair_flows(dpid, self.learned_cookie,
                                                    a, b)
                    self.flow_ops.delete_pair_flows(dpid, self.learned_cookie,
                                                    b, a)
        self.logger.info("[RECOVERY] FAILBACK_COMPLETE link=%s "
                         "(normal learning forwarding restored)",
                         self._fmt_link(key))

    def on_switch_removed(self, payload):
        dpid = payload["dpid"]
        for mac in [m for m, loc in self._hosts.items() if loc[0] == dpid]:
            del self._hosts[mac]
        self._isl_ports = set(p for p in self._isl_ports if p[0] != dpid)
        for key, session in list(self._sessions.items()):
            uses = any(dpid in e["path"] for e in session["pairs"].values())
            if uses or any(d == dpid for d, _ in key):
                self._close_session(key, "SESSION_INVALIDATED",
                                    "switch_removed dpid=%016x" % dpid)

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------
    @staticmethod
    def _edge_is(a, b, key):
        """(a, b) graph edge'i key ile tanımlanan link mi? nx.Graph iki
        switch arasında tek edge tuttuğundan DPID çifti yeterlidir."""
        return set((a, b)) == set(d for d, _ in key)

    def _uses(self, path, key):
        return any(self._edge_is(a, b, key) for a, b in zip(path, path[1:]))

    def _skip(self, trigger, reason, detail=""):
        self.logger.warning("[RECOVERY] SKIPPED trigger=%s reason=%s %s",
                            trigger, reason, detail)

    @staticmethod
    def _fmt(dpid):
        return "%016x" % dpid if isinstance(dpid, int) else repr(dpid)

    def _fmt_link(self, key):
        (a, pa), (b, pb) = sorted(key)
        return "%s:%s<->%s:%s" % (self._fmt(a), pa, self._fmt(b), pb)

    @staticmethod
    def _fmt_pair(pair):
        return "<->".join(sorted(pair))
