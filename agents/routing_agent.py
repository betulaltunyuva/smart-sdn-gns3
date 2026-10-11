"""
Smart SDN (GNS3) - Aşama 6: Routing Agent

LINK_FAILURE eventini alır ve arızalı linkin iki ucu arasında alternatif
yol arar. Ayrı graph veya shortest-path kodu YOKTUR: controller'ın canlı
TopologyManager örneği (topology.graph) ve onun get_shortest_path()
metodu kullanılır.

Controller bu zinciri graph güncellendikten sonra tetiklediği için arızalı
link graph'ta artık bulunmaz; bulunan yol gerçekten alternatif yoldur.

Yol bulunursa RECOVERY_REQUEST yayınlanır (flow kurulumu YOK).
"""

import logging

from utils.event_bus import LINK_FAILURE, RECOVERY_REQUEST


class RoutingAgent(object):

    def __init__(self, event_bus, topology, logger=None):
        self.bus = event_bus
        # Controller'ın TopologyManager örneği (None olabilir: NetworkX yok)
        self.topology = topology
        self.logger = logger or logging.getLogger(__name__)
        self.bus.subscribe(LINK_FAILURE, self.on_link_failure)

    def on_link_failure(self, link):
        src, dst = link["src_dpid"], link["dst_dpid"]
        if self.topology is None:
            self.logger.warning("[ROUTING] NO_ALTERNATIVE_PATH "
                                "src_dpid=%016x dst_dpid=%016x "
                                "reason=topology_disabled", src, dst)
            return

        # Mevcut shortest-path fonksiyonu; yol yoksa None döner ve kendi
        # NO_PATH logunu üretir.
        path = self.topology.get_shortest_path(src, dst)
        if path is None:
            self.logger.warning("[ROUTING] NO_ALTERNATIVE_PATH "
                                "src_dpid=%016x dst_dpid=%016x",
                                src, dst)
            return

        self.logger.info("[ROUTING] Alternative path calculated "
                         "src_dpid=%016x dst_dpid=%016x hop_count=%d "
                         "path=[%s]", src, dst, len(path) - 1,
                         ", ".join("%016x" % d for d in path))
        self.bus.publish(RECOVERY_REQUEST, {"failed_link": dict(link),
                                            "src_dpid": src,
                                            "dst_dpid": dst,
                                            "path": list(path)})
