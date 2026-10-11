"""
Aşama 6.3 - FailureDetectionAgent offline testi (GNS3/OS-Ken gerekmez).

Sentetik PORT_METRICS payload'ları EventBus'a enjekte edilir ve port
sağlık durumu geçişleri doğrulanır.

Çalıştırma (proje kökünden):
    python3 -m unittest -v tests.test_failure_agent_offline
"""

import logging
import unittest

from utils.event_bus import (EventBus, PORT_METRICS, PORT_HEALTH_CHANGED,
                             LINK_DOWN, LINK_UP, LINK_FAILURE,
                             TOPO_SWITCH_REMOVED)
from agents.failure_agent import (FailureDetectionAgent, HEALTHY, DEGRADED,
                                  FAILED)

DPID = 0x1
PORT = 2


class Sim(object):
    """Bir port için kümülatif sayaçları ilerleten sentetik kaynak."""

    def __init__(self, bus, dpid=DPID, port=PORT):
        self.bus, self.dpid, self.port = bus, dpid, port
        self.c = dict(rx_packets=0, tx_packets=0, rx_errors=0, tx_errors=0,
                      rx_dropped=0, tx_dropped=0)
        self.link_up = True

    def sample(self, rx=0, tx=0, rx_drop=0, rx_err=0):
        self.c["rx_packets"] += rx
        self.c["tx_packets"] += tx
        self.c["rx_dropped"] += rx_drop
        self.c["rx_errors"] += rx_err
        m = {"dpid": self.dpid, "port_no": self.port, "name": "eth%d" %
             self.port, "link_up": self.link_up, "admin_up": True,
             "interval_sec": 5.0}
        m.update(self.c)
        self.bus.publish(PORT_METRICS, m)


class FailureAgentOfflineTest(unittest.TestCase):

    def setUp(self):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.bus = EventBus()
        self.agent = FailureDetectionAgent(self.bus,
                                           logging.getLogger("test"))
        self.changes = []
        self.failures = []
        self.bus.subscribe(PORT_HEALTH_CHANGED, self.changes.append)
        self.bus.subscribe(LINK_FAILURE, self.failures.append)
        self.sim = Sim(self.bus)

    def state(self, dpid=DPID, port=PORT):
        return self.agent._ports[(dpid, port)]["state"]

    def test_degraded_and_recovery_sequence(self):
        s = self.sim
        s.sample()                          # baseline (delta yok)
        s.sample(rx=500, tx=500)            # normal
        self.assertEqual(self.state(), HEALTHY)

        s.sample(rx=500, tx=500, rx_drop=100)   # 1. anormal (~%17 drop)
        self.assertEqual(self.state(), HEALTHY,
                         "tek anormal örnek DEGRADED yapmamalı")
        s.sample(rx=500, tx=500, rx_drop=100)   # 2. anormal
        self.assertEqual(self.state(), DEGRADED)
        self.assertEqual(self.changes[-1]["new_state"], DEGRADED)
        self.assertEqual(self.changes[-1]["consecutive"], 2)

        s.sample(rx=500, tx=500)            # 1. normal
        self.assertEqual(self.state(), DEGRADED,
                         "tek normal örnek iyileştirmemeli")
        s.sample(rx=500, tx=500)            # 2. normal
        self.assertEqual(self.state(), HEALTHY)
        self.assertEqual(self.changes[-1]["old_state"], DEGRADED)
        self.assertEqual(len(self.changes), 2)

    def test_isolated_spikes_do_not_degrade(self):
        s = self.sim
        s.sample()
        for _ in range(5):                  # anormal / normal dönüşümlü
            s.sample(rx=500, rx_drop=100)
            s.sample(rx=500)
        self.assertEqual(self.state(), HEALTHY)
        self.assertEqual(self.changes, [])

    def test_errors_degrade(self):
        s = self.sim
        s.sample()
        s.sample(rx=1000, rx_err=20)        # ~%2 error
        s.sample(rx=1000, rx_err=20)
        self.assertEqual(self.state(), DEGRADED)

    def test_large_old_counters_and_idle_port_are_healthy(self):
        s = self.sim
        s.c.update(rx_dropped=10 ** 6, rx_errors=10 ** 5)  # eski büyük sayaç
        for _ in range(5):
            s.sample()                      # boşta, delta = 0
        s.sample(rx=3, rx_drop=3)           # çok düşük trafik
        s.sample(rx=3, rx_drop=3)
        self.assertEqual(self.state(), HEALTHY)
        self.assertEqual(self.changes, [])

    def test_port_down_failed_and_back(self):
        s = self.sim
        s.sample()
        s.link_up = False
        s.sample()
        self.assertEqual(self.state(), FAILED)
        s.sample()                          # tekrar log/event yok
        self.assertEqual(len(self.changes), 1)
        s.link_up = True
        s.sample(rx=100)
        self.assertEqual(self.state(), HEALTHY)
        self.assertEqual(self.failures, [],
                         "port_down LINK_FAILURE/routing tetiklememeli")

    def test_link_down_chain_and_link_up_clears(self):
        peer = Sim(self.bus, dpid=0x2, port=1)
        self.sim.sample()
        peer.sample()
        link = {"src_dpid": DPID, "src_port": PORT,
                "dst_dpid": 0x2, "dst_port": 1}
        self.bus.publish(LINK_DOWN, dict(link))
        self.assertEqual(len(self.failures), 1)    # zincir değişmedi
        self.assertEqual(self.failures[0], link)
        self.assertEqual(self.state(), FAILED)
        self.assertEqual(self.state(0x2, 1), FAILED)
        # GNS3 suspend: port fiziksel UP kalır, metrik FAILED'ı temizlemez
        self.sim.sample(rx=100)
        self.assertEqual(self.state(), FAILED)
        self.bus.publish(LINK_UP, dict(link))
        self.assertEqual(self.state(), HEALTHY)
        self.assertEqual(self.state(0x2, 1), HEALTHY)

    def test_switch_removed_cleans_state(self):
        self.sim.sample()
        Sim(self.bus, port=3).sample()
        self.bus.publish(TOPO_SWITCH_REMOVED, {"dpid": DPID})
        self.assertFalse(any(k[0] == DPID for k in self.agent._ports))
        # Switch silindikten sonra gelen LINK_DOWN stale kayıt yaratmaz
        self.bus.publish(LINK_DOWN, {"src_dpid": DPID, "src_port": PORT,
                                     "dst_dpid": 0x9, "dst_port": 1})
        self.assertEqual(self.agent._ports, {})
        self.assertEqual(len(self.failures), 1)


if __name__ == "__main__":
    unittest.main()
