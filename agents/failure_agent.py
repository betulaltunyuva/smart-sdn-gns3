"""
Smart SDN (GNS3) - Aşama 6 / 6.3: Failure Detection Agent

1) Aşama 6.1 (değişmedi): MonitoringAgent'ın LINK_DOWN eventlerini alır
   ve hemen LINK_FAILURE olarak onaylar (eşik/gecikme YOK). Zincir:
       LINK_DOWN -> LINK_FAILURE -> RoutingAgent -> RecoveryAgent

2) Aşama 6.3: MonitoringAgent'ın PORT_METRICS eventlerini değerlendirip
   (dpid, port) başına basit, KURAL TABANLI sağlık durumu tutar:
       HEALTHY  : port UP, kalıcı anormallik yok
       DEGRADED : port UP ama drop/error oranı ardışık örneklerde yüksek
       FAILED   : LINK_DOWN veya port link/admin DOWN
   Durum DEĞİŞİMLERİ loglanır ve PORT_HEALTH_CHANGED olarak yayınlanır.
   Bu event şu an yalnızca ileride kullanılmak üzere yayınlanır;
   DEGRADED routing/recovery tetiklemez.

Sayaçlar kümülatiftir: değerlendirme iki ardışık PORT_METRICS örneği
arasındaki FARKLAR (delta) üzerinden yapılır. Port başına yalnızca bir
önceki sayaç örneği tutulur. Eşikler sabittir ve laboratuvar ortamı için
seçilmiş geçici değerlerdir; "akıllı" veya evrensel olarak optimal
DEĞİLDİR, ileride AI tabanlı tespitle değiştirilebilir.
"""

import logging

from utils.event_bus import (LINK_UP, LINK_DOWN, LINK_FAILURE, PORT_METRICS,
                             PORT_HEALTH_CHANGED, TOPO_SWITCH_REMOVED)

# ----------------------------------------------------------------------
# Kural tabanlı eşikler (Aşama 6.3, geçici / laboratuvar için muhafazakâr)
# ----------------------------------------------------------------------
# Bir yöndeki (rx veya tx) drop oranı bu değere ulaşırsa örnek anormaldir
DROP_RATIO_THRESHOLD = 0.05      # %5
# Bir yöndeki (rx veya tx) error oranı bu değere ulaşırsa örnek anormaldir
ERROR_RATIO_THRESHOLD = 0.01     # %1
# Oran hesaplamak için bir yönde, bir örnek aralığında gereken en az paket
# (iyi + kötü). Daha az trafik varsa o yön değerlendirilmez (boşta port).
MIN_PACKETS_FOR_RATIO = 20
# Oranın anlamlı sayılması için aralıkta en az bu kadar drop/error olmalı
MIN_BAD_PACKETS = 5
# HEALTHY -> DEGRADED için gereken ardışık anormal örnek sayısı
DEGRADE_AFTER_SAMPLES = 2
# DEGRADED -> HEALTHY için gereken ardışık normal örnek sayısı
RECOVER_AFTER_SAMPLES = 2

# Sağlık durumları
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"

# Delta hesabı için önceki örnekte saklanan kümülatif sayaçlar
_COUNTERS = ("rx_packets", "tx_packets", "rx_errors", "tx_errors",
             "rx_dropped", "tx_dropped")


class FailureDetectionAgent(object):

    def __init__(self, event_bus, logger=None):
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        # Aşama 6.3 port durumu:
        #   _ports: {(dpid, port_no): {
        #       "state": HEALTHY | DEGRADED | FAILED,
        #       "reason": FAILED sebebi ("link_down" | "port_down") veya None,
        #       "abnormal": ardışık anormal örnek sayısı,
        #       "normal": ardışık normal örnek sayısı,
        #       "prev": {sayaç: int|None} bir önceki kümülatif örnek}}
        self._ports = {}
        self.bus.subscribe(LINK_DOWN, self.on_link_down)
        self.bus.subscribe(LINK_UP, self.on_link_up)
        self.bus.subscribe(PORT_METRICS, self.on_port_metrics)
        self.bus.subscribe(TOPO_SWITCH_REMOVED, self.on_switch_removed)

    # ------------------------------------------------------------------
    # Aşama 6.1: link arızası (anında onaylanır, değişmedi)
    # ------------------------------------------------------------------
    def on_link_down(self, link):
        self.logger.info("[FAILURE] LINK_FAILURE confirmed "
                         "src_dpid=%016x dst_dpid=%016x reason=link_down",
                         link["src_dpid"], link["dst_dpid"])
        self.bus.publish(LINK_FAILURE, dict(link))
        # Aşama 6.3: linkin iki ucundaki portlar FAILED olarak işaretlenir
        for dpid, port_no in self._link_ends(link):
            entry = self._entry_if_known(dpid, port_no)
            if entry is not None:
                self._set_state(dpid, port_no, entry, FAILED,
                                reason="link_down")

    def on_link_up(self, link):
        """Link (yeniden) keşfedildi: uçlarındaki FAILED durumu temizlenir.
        Başlangıçtaki ilk LINK_UP'larda port zaten HEALTHY olduğundan
        log üretilmez."""
        for dpid, port_no in self._link_ends(link):
            entry = self._ports.get((dpid, port_no))
            if entry is not None and entry["state"] == FAILED:
                self._set_state(dpid, port_no, entry, HEALTHY,
                                reason="link_up")

    @staticmethod
    def _link_ends(link):
        return ((link.get("src_dpid"), link.get("src_port")),
                (link.get("dst_dpid"), link.get("dst_port")))

    def _entry_if_known(self, dpid, port_no):
        """Port kaydını döner; yoksa yalnızca switch zaten biliniyorsa
        oluşturur. Böylece switch silindikten SONRA gelen LINK_DOWN'lar
        silinmiş switch için eski (stale) kayıt yaratmaz."""
        key = (dpid, port_no)
        if key not in self._ports:
            if not any(k[0] == dpid for k in self._ports):
                return None
            self._ports[key] = self._new_entry()
        return self._ports[key]

    @staticmethod
    def _new_entry():
        return {"state": HEALTHY, "reason": None, "abnormal": 0,
                "normal": 0, "prev": None}

    # ------------------------------------------------------------------
    # Aşama 6.3: switch temizliği
    # ------------------------------------------------------------------
    def on_switch_removed(self, payload):
        dpid = payload["dpid"]
        for key in [k for k in self._ports if k[0] == dpid]:
            del self._ports[key]

    # ------------------------------------------------------------------
    # Aşama 6.3: metrik tabanlı port sağlığı
    # ------------------------------------------------------------------
    def on_port_metrics(self, m):
        """m: MonitoringAgent PORT_METRICS payload'ı (dpid, port_no,
        link_up, admin_up ve kümülatif rx/tx packets/errors/dropped)."""
        dpid, port_no = m["dpid"], m["port_no"]
        entry = self._ports.setdefault((dpid, port_no), self._new_entry())

        deltas = self._deltas(entry, m)

        # Port durumu: link veya admin DOWN -> anında FAILED.
        # None (PortDesc henüz gelmedi) bilinmiyor demektir, DOWN sayılmaz.
        if m.get("link_up") is False or m.get("admin_up") is False:
            if entry["state"] != FAILED:
                self._set_state(dpid, port_no, entry, FAILED,
                                reason="port_down")
            return
        if entry["state"] == FAILED:
            # link_down kaynaklı FAILED yalnızca LINK_UP ile temizlenir
            # (GNS3'te link askıya alınınca port fiziksel olarak UP kalır).
            if entry["reason"] != "port_down":
                return
            self._set_state(dpid, port_no, entry, HEALTHY, reason="port_up")

        # İlk örnek veya sayaç sıfırlanması: yalnızca baseline
        if deltas is None:
            return

        drop_ratio = max(self._ratio(deltas["rx_dropped"],
                                     deltas["rx_packets"]),
                         self._ratio(deltas["tx_dropped"],
                                     deltas["tx_packets"]))
        error_ratio = max(self._ratio(deltas["rx_errors"],
                                      deltas["rx_packets"]),
                          self._ratio(deltas["tx_errors"],
                                      deltas["tx_packets"]))
        abnormal = (drop_ratio >= DROP_RATIO_THRESHOLD or
                    error_ratio >= ERROR_RATIO_THRESHOLD)

        if abnormal:
            entry["abnormal"] += 1
            entry["normal"] = 0
        else:
            entry["normal"] += 1
            entry["abnormal"] = 0

        if (entry["state"] == HEALTHY and
                entry["abnormal"] >= DEGRADE_AFTER_SAMPLES):
            self._set_state(dpid, port_no, entry, DEGRADED,
                            reason="drop_error_ratio",
                            drop_ratio=drop_ratio, error_ratio=error_ratio)
        elif (entry["state"] == DEGRADED and
                entry["normal"] >= RECOVER_AFTER_SAMPLES):
            self._set_state(dpid, port_no, entry, HEALTHY,
                            reason="metrics_normal",
                            drop_ratio=drop_ratio, error_ratio=error_ratio)

    @staticmethod
    def _deltas(entry, m):
        """Kümülatif sayaçları kaydeder ve önceki örneğe göre farkları
        döner. Önceki örnek yoksa veya herhangi bir sayaç geriye gittiyse
        (sıfırlanma) None döner. Desteklenmeyen (None) sayaçların farkı 0
        kabul edilir."""
        cur = dict((name, m.get(name)) for name in _COUNTERS)
        prev, entry["prev"] = entry["prev"], cur
        if prev is None:
            return None
        deltas = {}
        for name in _COUNTERS:
            if cur[name] is None or prev[name] is None:
                deltas[name] = 0
            elif cur[name] < prev[name]:
                return None
            else:
                deltas[name] = cur[name] - prev[name]
        return deltas

    @staticmethod
    def _ratio(bad, good):
        """bad / (good + bad). Trafik veya kötü paket sayısı anlamlı
        olmayacak kadar azsa 0.0 döner (boşta port alarm üretmez)."""
        total = good + bad
        if total < MIN_PACKETS_FOR_RATIO or bad < MIN_BAD_PACKETS:
            return 0.0
        return float(bad) / total

    def _set_state(self, dpid, port_no, entry, new_state, reason,
                   drop_ratio=None, error_ratio=None):
        """Durum geçişini uygular, loglar ve PORT_HEALTH_CHANGED yayınlar."""
        old_state = entry["state"]
        consecutive = (entry["abnormal"] if new_state == DEGRADED
                       else entry["normal"])
        entry["state"] = new_state
        entry["reason"] = reason if new_state == FAILED else None
        entry["abnormal"] = 0
        entry["normal"] = 0

        if new_state == DEGRADED:
            self.logger.warning("[FAILURE] PORT_DEGRADED dpid=%016x port=%s "
                                "drop_ratio=%.3f error_ratio=%.3f "
                                "consecutive=%d", dpid, port_no,
                                drop_ratio, error_ratio, consecutive)
        elif new_state == FAILED:
            self.logger.warning("[FAILURE] PORT_FAILED dpid=%016x port=%s "
                                "previous=%s reason=%s",
                                dpid, port_no, old_state, reason)
        else:
            self.logger.info("[FAILURE] PORT_RECOVERED dpid=%016x port=%s "
                             "state=HEALTHY previous=%s reason=%s",
                             dpid, port_no, old_state, reason)

        self.bus.publish(PORT_HEALTH_CHANGED, {
            "dpid": dpid, "port_no": port_no,
            "old_state": old_state, "new_state": new_state,
            "reason": reason, "drop_ratio": drop_ratio,
            "error_ratio": error_ratio, "consecutive": consecutive})
