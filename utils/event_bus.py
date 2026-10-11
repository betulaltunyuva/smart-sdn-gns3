"""
Smart SDN (GNS3) - Aşama 6: hafif, process-içi EventBus

Agentlar birbirini doğrudan çağırmaz; event adına subscribe olur ve
publish edilen eventleri callback ile alır. Harici framework yoktur
(SPADE/RabbitMQ/Kafka kullanılmaz).

Teslim senkron ve FIFO sıralıdır: publish(), o event'in tüm
subscriber'larını çağırdıktan sonra döner. Bir subscriber içinden yapılan
publish (ör. Monitoring -> Failure) hemen işlenir; böylece zincir tek bir
OS-Ken handler çağrısı içinde, sıralı olarak tamamlanır.

Bir subscriber exception fırlatırsa loglanır ve diğer subscriber'lar
çalışmaya devam eder; agent hatası controller'ı durdurmaz.
"""

import logging


# ----------------------------------------------------------------------
# Event adları (tek yerde tanımlı; agentlar bunları kullanır)
# ----------------------------------------------------------------------
# Controller -> MonitoringAgent
TOPO_LINK_ADDED = "TOPO_LINK_ADDED"
TOPO_LINK_REMOVED = "TOPO_LINK_REMOVED"
# MonitoringAgent -> FailureDetectionAgent
LINK_UP = "LINK_UP"
LINK_DOWN = "LINK_DOWN"
# FailureDetectionAgent -> RoutingAgent
LINK_FAILURE = "LINK_FAILURE"
# RoutingAgent -> RecoveryAgent
RECOVERY_REQUEST = "RECOVERY_REQUEST"


class EventBus(object):
    """Event adı -> callback listesi eşlemesi tutan basit pub/sub bus."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        # {event_name: [callback, ...]}
        self._subscribers = {}

    def subscribe(self, event_name, callback):
        """callback(payload) fonksiyonunu event_name için kaydeder."""
        callbacks = self._subscribers.setdefault(event_name, [])
        if callback not in callbacks:
            callbacks.append(callback)

    def unsubscribe(self, event_name, callback):
        callbacks = self._subscribers.get(event_name, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def publish(self, event_name, payload=None):
        """event_name'e abone olan tüm callback'leri payload (dict) ile
        çağırır. Çağrılan subscriber sayısını döner."""
        if payload is None:
            payload = {}
        callbacks = list(self._subscribers.get(event_name, []))
        for callback in callbacks:
            try:
                callback(payload)
            except Exception:
                self.logger.exception("EVENT_BUS subscriber hatası "
                                      "event=%s callback=%r",
                                      event_name, callback)
        return len(callbacks)
