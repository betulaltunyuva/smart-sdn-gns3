"""
Smart SDN (GNS3) - Topoloji graph yöneticisi
  - Aşama 4.3: Keşfedilen switch ve linklerden dinamik NetworkX graph
  - Aşama 5.1: Graph üzerinden dinamik shortest path (yalnızca hesaplama)

Bu modül OS-Ken'e ve controller'a bağımlı değildir (circular import yok).
Controller, kendi tuttuğu aktif switch (datapaths) ve fiziksel link (links)
verilerini sync() ile buraya verir; graph bu verilerden güncellenir.

Graph modeli (nx.Graph, yönsüz):
  - Node : switch DPID'si (int)
  - Edge : bir fiziksel switch-switch linki (A-B tek edge)
           Attribute'lar:
             src_dpid, src_port, dst_dpid, dst_port  (linkin ilk keşfedilen yönü)
             ports = {dpid: port_no}  (her uçtaki yerel port; yönden bağımsız)
"""

import logging

import networkx as nx


class TopologyManager(object):
    """Controller'ın keşfettiği switch/linklerden graph üretir ve günceller."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.graph = nx.Graph()

    # ------------------------------------------------------------------
    # Node işlemleri
    # ------------------------------------------------------------------
    def add_switch(self, dpid):
        if self.graph.has_node(dpid):
            return False
        self.graph.add_node(dpid)
        return True

    def remove_switch(self, dpid):
        if not self.graph.has_node(dpid):
            return False
        # networkx node'a bağlı edge'leri de kaldırır
        self.graph.remove_node(dpid)
        return True

    # ------------------------------------------------------------------
    # Edge işlemleri
    # ------------------------------------------------------------------
    def add_link(self, src_dpid, src_port, dst_dpid, dst_port):
        """Fiziksel linki tek (yönsüz) edge olarak ekler/günceller."""
        attrs = {"src_dpid": src_dpid, "src_port": src_port,
                 "dst_dpid": dst_dpid, "dst_port": dst_port,
                 "ports": {src_dpid: src_port, dst_dpid: dst_port}}
        if self.graph.has_edge(src_dpid, dst_dpid):
            if self.graph.edges[src_dpid, dst_dpid]["ports"] == attrs["ports"]:
                return False
            self.graph.edges[src_dpid, dst_dpid].update(attrs)
            return True
        self.graph.add_edge(src_dpid, dst_dpid, **attrs)
        return True

    def remove_link(self, src_dpid, dst_dpid):
        if not self.graph.has_edge(src_dpid, dst_dpid):
            return False
        self.graph.remove_edge(src_dpid, dst_dpid)
        return True

    # ------------------------------------------------------------------
    # Controller verisinden senkronizasyon (tek doğru kaynak: controller)
    # ------------------------------------------------------------------
    def sync(self, datapaths, links):
        """Graph'ı controller'ın güncel verisine eşitler.

        datapaths: {dpid: datapath}  (yalnızca anahtarlar kullanılır)
        links:     {key: {"src_dpid", "src_port", "dst_dpid", "dst_port"}}
        Değişiklik olduysa True döner.
        """
        changed = False
        active = set(datapaths)

        for dpid in list(self.graph.nodes):
            if dpid not in active:
                changed |= self.remove_switch(dpid)
        for dpid in active:
            changed |= self.add_switch(dpid)

        # Yalnızca iki ucu da aktif switch olan linkler edge olur. Switch
        # koptuğunda link silme eventleri birazdan gelir; bu arada graph'ta
        # olmayan bir node'a edge eklenmez.
        wanted = {}
        for info in links.values():
            u, v = info["src_dpid"], info["dst_dpid"]
            if u in active and v in active:
                # Aynı iki switch arasında paralel link varsa nx.Graph bunları
                # tek edge'e indirger; deterministik olarak ilki tutulur.
                wanted.setdefault(frozenset((u, v)), info)

        for u, v in list(self.graph.edges):
            if frozenset((u, v)) not in wanted:
                changed |= self.remove_link(u, v)
        for info in wanted.values():
            changed |= self.add_link(info["src_dpid"], info["src_port"],
                                     info["dst_dpid"], info["dst_port"])
        return changed

    # ------------------------------------------------------------------
    # Shortest path (Aşama 5.1)
    # Her çağrı self.graph'ın o anki halini kullanır; sonuç saklanmaz, bu
    # yüzden switch/link eklenip silindikten sonraki hesap yeni graph'a
    # göre yapılır. Yalnızca hesaplama yapılır, flow kurulmaz.
    # ------------------------------------------------------------------
    def path_exists(self, src_dpid, dst_dpid):
        """İki switch arasında graph üzerinde yol varsa True döner."""
        if (not self.graph.has_node(src_dpid)
                or not self.graph.has_node(dst_dpid)):
            return False
        return nx.has_path(self.graph, src_dpid, dst_dpid)

    def get_shortest_path(self, src_dpid, dst_dpid):
        """En az hop'lu yolu DPID listesi olarak döner, yol yoksa None.

        Kaynak ve hedef aynı (graph'ta bulunan) switch ise [src_dpid] döner.
        Exception fırlatmaz; yol bulunamayan her durum NO_PATH olarak loglanır.
        """
        for dpid in (src_dpid, dst_dpid):
            if not self.graph.has_node(dpid):
                self._log_no_path(src_dpid, dst_dpid,
                                  "dpid_not_in_graph=%s" % self._fmt(dpid))
                return None
        try:
            path = nx.shortest_path(self.graph, src_dpid, dst_dpid)
        except nx.NetworkXNoPath:
            self._log_no_path(src_dpid, dst_dpid, "disconnected")
            return None
        self.logger.info("SHORTEST_PATH src_dpid=%s dst_dpid=%s "
                         "hop_count=%d path=[%s]",
                         self._fmt(src_dpid), self._fmt(dst_dpid),
                         len(path) - 1,
                         ", ".join(self._fmt(d) for d in path))
        return path

    def _log_no_path(self, src_dpid, dst_dpid, reason):
        self.logger.warning("NO_PATH src_dpid=%s dst_dpid=%s reason=%s",
                            self._fmt(src_dpid), self._fmt(dst_dpid), reason)

    @staticmethod
    def _fmt(dpid):
        # Graph DPID'leri int'tir; beklenmeyen tip gelirse log yine üretilsin
        if isinstance(dpid, int):
            return "%016x" % dpid
        return repr(dpid)

    # ------------------------------------------------------------------
    # Okuma / çıktı
    # ------------------------------------------------------------------
    def node_count(self):
        return self.graph.number_of_nodes()

    def edge_count(self):
        return self.graph.number_of_edges()

    def format_graph(self):
        nodes = ", ".join("%016x" % dpid for dpid in sorted(self.graph.nodes))
        edges = []
        for u, v, data in sorted(self.graph.edges(data=True),
                                 key=lambda e: tuple(sorted(e[:2]))):
            a, b = sorted((u, v))
            edges.append("(%016x:%s <-> %016x:%s)"
                         % (a, data["ports"][a], b, data["ports"][b]))
        return ("TOPOLOGY_GRAPH node_count=%d edge_count=%d "
                "nodes=[%s] edges=[%s]"
                % (self.node_count(), self.edge_count(),
                   nodes, ", ".join(edges)))

    def log_graph(self):
        self.logger.info(self.format_graph())
