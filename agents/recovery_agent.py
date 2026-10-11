"""
Smart SDN (GNS3) - Aşama 6: Recovery Agent

RoutingAgent'ın RECOVERY_REQUEST eventini alır ve YALNIZCA loglar.
Bu aşamada OpenFlow flow kurulumu / değişikliği ve gerçek trafik
yönlendirmesi YAPILMAZ (sonraki adımda eklenecek).
"""

import logging

from utils.event_bus import RECOVERY_REQUEST


class RecoveryAgent(object):

    def __init__(self, event_bus, logger=None):
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        self.bus.subscribe(RECOVERY_REQUEST, self.on_recovery_request)

    def on_recovery_request(self, request):
        self.logger.info("[RECOVERY] Recovery request received "
                         "src_dpid=%016x dst_dpid=%016x path=[%s] "
                         "(log only, no flow changes)",
                         request["src_dpid"], request["dst_dpid"],
                         ", ".join("%016x" % d for d in request["path"]))
