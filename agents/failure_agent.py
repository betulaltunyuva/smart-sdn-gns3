"""
Smart SDN (GNS3) - Aşama 6: Failure Detection Agent

MonitoringAgent'ın LINK_DOWN eventlerini alır ve LINK_FAILURE olarak
onaylar. Bu aşamada LINK_DOWN (yani controller'daki LINK_REMOVED) doğrudan
onaylanmış link arızası kabul edilir; AI/anomali tespiti YOKTUR.
"""

import logging

from utils.event_bus import LINK_DOWN, LINK_FAILURE


class FailureDetectionAgent(object):

    def __init__(self, event_bus, logger=None):
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        self.bus.subscribe(LINK_DOWN, self.on_link_down)

    def on_link_down(self, link):
        self.logger.info("[FAILURE] LINK_FAILURE confirmed "
                         "src_dpid=%016x dst_dpid=%016x",
                         link["src_dpid"], link["dst_dpid"])
        self.bus.publish(LINK_FAILURE, dict(link))
