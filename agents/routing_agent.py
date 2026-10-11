"""
Smart SDN (GNS3) - Aşama 6 / 6.4: Routing Agent (kural tabanlı karar motoru)

Alternatif yol kararlarını controller'ın canlı TopologyManager graph'ı
(topology.graph) üzerinden verir. Sabit DPID/port/yol YOKTUR.

Tetikleyiciler:
  1) LINK_FAILURE (FailureDetectionAgent, Aşama 6.1): arızalı link graph'tan
     zaten çıkarılmıştır; iki ucu arasında kalan graph'ta yol aranır.
  2) PORT_HEALTH_CHANGED -> DEGRADED (Aşama 6.3): link graph'ta FİZİKSEL
     OLARAK DURUR; yalnızca bu hesap için geçici olarak hariç tutulur.
     Port bir switch-switch linkine ait değilse (host portu) yol hesabı
     yapılmaz. DEGRADED -> HEALTHY yalnızca loglanır (failback YOK).

Karar kuralı (deterministik):
  - Arızalı / DEGRADED tetikleyici edge hariç tutulur.
  - Önce bilinen diğer DEGRADED edge'ler de hariç tutulur; bu durumda yol
    yoksa yalnızca tetikleyici edge hariç tutularak tekrar denenir
    (DEGRADED link, hiç yol olmamasından iyidir).
  - En az hop'lu yollar arasından DPID listesi sözlük sırasına göre en
    küçük olan seçilir (rastgelelik yok).

Canlı graph DEĞİŞTİRİLMEZ: hariç tutma networkx.restricted_view ile salt
okunur bir görünüm üzerinden yapılır.

Yol bulunursa RECOVERY_REQUEST yayınlanır (flow kurulumu YOK; Aşama 6.5).
Yol yoksa yalnızca NO_ALTERNATIVE_PATH loglanır, istek gönderilmez.
"""

import logging

try:
    import networkx as nx
except ImportError:          # controller topology_disabled durumunu loglar
    nx = None

from utils.event_bus import (LINK_FAILURE, RECOVERY_REQUEST,
                             PORT_HEALTH_CHANGED, TOPO_SWITCH_REMOVED)

# FailureDetectionAgent sağlık durumları (PORT_HEALTH_CHANGED payload'ı)
_DEGRADED = "DEGRADED"

TRIGGER_LINK_FAILURE = "LINK_FAILURE"
TRIGGER_PORT_DEGRADED = "PORT_DEGRADED"


class RoutingAgent(object):

    def __init__(self, event_bus, topology, logger=None):
        self.bus = event_bus
        # Controller'ın TopologyManager örneği (None olabilir: NetworkX yok)
        self.topology = topology
        self.logger = logger or logging.getLogger(__name__)
        # DEGRADED switch-switch linkleri:
        #   {link_key: set((dpid, port_no), ...)}  link_key = frozenset of
        #   iki uç (dpid, port_no). Değer, linki DEGRADED bildiren uçlardır.
        self._degraded = {}
        self.bus.subscribe(LINK_FAILURE, self.on_link_failure)
        self.bus.subscribe(PORT_HEALTH_CHANGED, self.on_port_health_changed)
        self.bus.subscribe(TOPO_SWITCH_REMOVED, self.on_switch_removed)

    # ------------------------------------------------------------------
    # Tetikleyici 1: onaylanmış link arızası
    # ------------------------------------------------------------------
    def on_link_failure(self, link):
        src, dst = link["src_dpid"], link["dst_dpid"]
        link_key = frozenset(((src, link.get("src_port")),
                              (dst, link.get("dst_port"))))
        # Arızalı link artık DEGRADED takibinde de olmamalı
        self._degraded.pop(link_key, None)
        self._decide(TRIGGER_LINK_FAILURE, "link_down", link_key, link,
                     extra={"failed_link": dict(link)})

    # ------------------------------------------------------------------
    # Tetikleyici 2: port sağlık değişimi
    # ------------------------------------------------------------------
    def on_port_health_changed(self, event):
        dpid, port_no = event["dpid"], event["port_no"]
        port = (dpid, port_no)
        old, new = event.get("old_state"), event.get("new_state")

        if new == _DEGRADED:
            self._on_port_degraded(port, event)
        elif old == _DEGRADED:
            # DEGRADED -> HEALTHY/FAILED: DEGRADED işareti kaldırılır.
            # FAILED durumunu LINK_FAILURE zinciri ayrıca işler.
            self._clear_degraded_port(port, new)

    def _on_port_degraded(self, port, event):
        dpid, port_no = port
        link_key = self._link_key_for_port(dpid, port_no)
        if link_key is None:
            self.logger.info("[ROUTING] DEGRADED_HOST_PORT ignored "
                             "dpid=%016x port=%s (not an inter-switch link)",
                             dpid, port_no)
            return

        reporters = self._degraded.get(link_key)
        if reporters is not None:
            # Aynı link için karar zaten verildi (tekrar eden event veya
            # linkin diğer ucu da DEGRADED oldu): yeni istek yayınlanmaz.
            reporters.add(port)
            self.logger.info("[ROUTING] DEGRADED_DUPLICATE ignored "
                             "dpid=%016x port=%s link=%s",
                             dpid, port_no, self._fmt_link(link_key))
            return
        self._degraded[link_key] = set([port])

        # Yön: DEGRADED bildiren switch -> linkin diğer ucu
        (peer_dpid, peer_port), = link_key - set([port])
        link = {"src_dpid": dpid, "src_port": port_no,
                "dst_dpid": peer_dpid, "dst_port": peer_port}
        self._decide(TRIGGER_PORT_DEGRADED, "metrics", link_key, link,
                     extra={"degraded_port": {"dpid": dpid,
                                              "port_no": port_no},
                            "drop_ratio": event.get("drop_ratio"),
                            "error_ratio": event.get("error_ratio")})

    def _clear_degraded_port(self, port, new_state):
        for link_key, reporters in list(self._degraded.items()):
            if port not in reporters:
                continue
            reporters.discard(port)
            if reporters:
                continue      # diğer uç hâlâ DEGRADED
            del self._degraded[link_key]
            self.logger.info("[ROUTING] DEGRADED_CONDITION_CLEARED "
                             "dpid=%016x port=%s link=%s state=%s "
                             "(no automatic failback)",
                             port[0], port[1], self._fmt_link(link_key),
                             new_state)

    def on_switch_removed(self, payload):
        dpid = payload["dpid"]
        for link_key in [k for k in self._degraded
                         if any(d == dpid for d, _ in k)]:
            del self._degraded[link_key]

    # ------------------------------------------------------------------
    # Karar motoru
    # ------------------------------------------------------------------
    def _decide(self, trigger, reason, link_key, link, extra):
        src, dst = link["src_dpid"], link["dst_dpid"]
        if self.topology is None or nx is None:
            self._no_path(trigger, src, dst, "topology_disabled")
            return

        graph = self.topology.graph
        for dpid in (src, dst):
            if not graph.has_node(dpid):
                self._no_path(trigger, src, dst, "dpid_not_in_graph")
                return

        trigger_edges = self._edges_in_graph([link_key])
        other_degraded = self._edges_in_graph(
            k for k in self._degraded if k != link_key)

        # Önce diğer DEGRADED linklerden de kaçın; olmazsa yalnızca
        # tetikleyici link hariç tutulur.
        path, avoided = None, []
        attempts = [trigger_edges + other_degraded]
        if other_degraded:
            attempts.append(trigger_edges)
        for excluded in attempts:
            path = self._shortest_path(graph, src, dst, excluded)
            if path is not None:
                avoided = excluded
                break
        if path is None:
            self._no_path(trigger, src, dst, "disconnected")
            return

        hop_count = len(path) - 1
        self.logger.info("[ROUTING] ALTERNATIVE_PATH trigger=%s reason=%s "
                         "src_dpid=%016x dst_dpid=%016x hop_count=%d "
                         "path=[%s] excluded_edges=%d",
                         trigger, reason, src, dst, hop_count,
                         ", ".join("%016x" % d for d in path), len(avoided))
        request = {"trigger": trigger, "reason": reason,
                   "src_dpid": src, "dst_dpid": dst,
                   "affected_link": dict(link),
                   "path": list(path), "hop_count": hop_count,
                   "excluded_edges": [tuple(sorted(e)) for e in avoided]}
        request.update(extra)
        self.bus.publish(RECOVERY_REQUEST, request)

    @staticmethod
    def _shortest_path(graph, src, dst, excluded_edges):
        """Canlı graph'ı DEĞİŞTİRMEDEN, excluded_edges gizlenmiş salt okunur
        görünümde en az hop'lu yolu döner (eşitlikte sözlük sırasına göre
        en küçük DPID listesi). Yol yoksa None."""
        view = nx.restricted_view(graph, [], excluded_edges)
        try:
            return min(nx.all_shortest_paths(view, src, dst))
        except nx.NetworkXNoPath:
            return None

    def _edges_in_graph(self, link_keys):
        """link_key'leri graph'ta bulunan ve portları eşleşen (u, v)
        edge'lerine çevirir."""
        graph = self.topology.graph
        edges = []
        for link_key in link_keys:
            (a, pa), (b, pb) = sorted(link_key)
            if (graph.has_edge(a, b) and
                    graph.edges[a, b]["ports"] == {a: pa, b: pb}):
                edges.append((a, b))
        return edges

    def _link_key_for_port(self, dpid, port_no):
        """(dpid, port) bir switch-switch linkine aitse linkin iki ucunu
        frozenset olarak döner; host portuysa None."""
        if self.topology is None or nx is None:
            return None
        graph = self.topology.graph
        if not graph.has_node(dpid):
            return None
        for nbr in sorted(graph.adj[dpid]):
            ports = graph.edges[dpid, nbr]["ports"]
            if ports.get(dpid) == port_no:
                return frozenset(((dpid, port_no), (nbr, ports[nbr])))
        return None

    def _no_path(self, trigger, src, dst, reason):
        self.logger.warning("[ROUTING] NO_ALTERNATIVE_PATH trigger=%s "
                            "src_dpid=%016x dst_dpid=%016x reason=%s",
                            trigger, src, dst, reason)

    @staticmethod
    def _fmt_link(link_key):
        (a, pa), (b, pb) = sorted(link_key)
        return "%016x:%s<->%016x:%s" % (a, pa, b, pb)
