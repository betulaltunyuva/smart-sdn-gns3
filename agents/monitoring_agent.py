"""
Smart SDN (GNS3) - Aşama 6: Monitoring Agent

Controller'ın bildirdiği topoloji/link durumunu izler ve monitoring
eventleri yayınlar:
    TOPO_LINK_ADDED   -> LINK_UP
    TOPO_LINK_REMOVED -> LINK_DOWN

Bu aşamada latency/throughput/packet loss ölçümü YOKTUR.
"""

import logging

from utils.event_bus import (TOPO_LINK_ADDED, TOPO_LINK_REMOVED,
                             LINK_UP, LINK_DOWN)


class MonitoringAgent(object):

    def __init__(self, event_bus, logger=None):
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        self.bus.subscribe(TOPO_LINK_ADDED, self.on_link_added)
        self.bus.subscribe(TOPO_LINK_REMOVED, self.on_link_removed)

    def on_link_added(self, link):
        self.logger.info("[MONITORING] LINK_UP detected "
                         "src_dpid=%016x dst_dpid=%016x",
                         link["src_dpid"], link["dst_dpid"])
        self.bus.publish(LINK_UP, dict(link))

    def on_link_removed(self, link):
        self.logger.info("[MONITORING] LINK_DOWN detected "
                         "src_dpid=%016x src_port=%s "
                         "dst_dpid=%016x dst_port=%s",
                         link["src_dpid"], link["src_port"],
                         link["dst_dpid"], link["dst_port"])
        self.bus.publish(LINK_DOWN, dict(link))
