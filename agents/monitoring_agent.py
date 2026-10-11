"""
Smart SDN (GNS3) - Aşama 6 / 6.2: Monitoring Agent

1) Controller'ın bildirdiği topoloji/link durumunu izler ve monitoring
   eventleri yayınlar (Aşama 6.1, değişmedi):
       TOPO_LINK_ADDED   -> LINK_UP
       TOPO_LINK_REMOVED -> LINK_DOWN

2) Aşama 6.2: Controller'ın periyodik olarak topladığı OpenFlow 1.3 port
   bilgilerini işler:
       PORT_STATUS_UPDATE (OFPPortDescStatsReply) -> port link/admin durumu
       PORT_STATS_UPDATE  (OFPPortStatsReply)     -> sayaçlar + hız hesabı
   Her port için hesaplanan metrikler loglanır ve PORT_METRICS olarak
   yayınlanır (şu an subscriber yok; eşik/AI tespiti YOKTUR).

Hızlar yalnızca iki ardışık örneğin farkından hesaplanır; tek örnekten
hız üretilmez. Port başına yalnızca bir önceki sayaç örneği tutulur.

Bu aşamada latency (ping) ve packet loss ölçümü YOKTUR.
"""

import logging
import time

from utils.event_bus import (TOPO_LINK_ADDED, TOPO_LINK_REMOVED,
                             LINK_UP, LINK_DOWN,
                             PORT_STATUS_UPDATE, PORT_STATS_UPDATE,
                             TOPO_SWITCH_REMOVED, PORT_METRICS)

# OpenFlow'da desteklenmeyen sayaçlar tüm bitleri 1 olarak raporlanır
_UNSUPPORTED_COUNTER = 0xffffffffffffffff

# Hız hesabında kullanılan sayaçlar
_RATE_COUNTERS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets")
# Ham olarak raporlanan sayaçlar
_ALL_COUNTERS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
                 "rx_errors", "tx_errors", "rx_dropped", "tx_dropped")


class MonitoringAgent(object):

    def __init__(self, event_bus, logger=None):
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        # Aşama 6.2 durum bilgisi (minimum):
        #   _prev_samples: {(dpid, port_no): {"t": float, "rx_bytes": int,
        #                   "tx_bytes": int, "rx_packets": int,
        #                   "tx_packets": int}}
        #       Hız hesabı için yalnızca bir önceki örnek.
        #   _port_status: {(dpid, port_no): {"name": str, "link_up": bool,
        #                  "admin_up": bool}}
        #       Son PortDesc cevabındaki port durumu.
        self._prev_samples = {}
        self._port_status = {}
        self.bus.subscribe(TOPO_LINK_ADDED, self.on_link_added)
        self.bus.subscribe(TOPO_LINK_REMOVED, self.on_link_removed)
        self.bus.subscribe(PORT_STATUS_UPDATE, self.on_port_status)
        self.bus.subscribe(PORT_STATS_UPDATE, self.on_port_stats)
        self.bus.subscribe(TOPO_SWITCH_REMOVED, self.on_switch_removed)

    # ------------------------------------------------------------------
    # Aşama 6.1: link durumu
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Aşama 6.2: port durumu ve istatistikleri
    # ------------------------------------------------------------------
    def on_switch_removed(self, payload):
        """Kopan switch'e ait eski örnekleri sil; yeniden bağlandığında
        hız hesabı yeni bir baseline ile başlar."""
        dpid = payload["dpid"]
        for store in (self._prev_samples, self._port_status):
            for key in [k for k in store if k[0] == dpid]:
                del store[key]

    def on_port_status(self, payload):
        """payload: {"dpid": int, "ports": [{"port_no", "name", "link_up",
        "admin_up"}, ...]} (yalnızca veri portları)."""
        dpid = payload["dpid"]
        for port in payload["ports"]:
            self._port_status[(dpid, port["port_no"])] = {
                "name": port.get("name"),
                "link_up": port.get("link_up"),
                "admin_up": port.get("admin_up")}

    def on_port_stats(self, payload):
        """payload: {"dpid": int, "timestamp": float (monotonic),
        "ports": [{"port_no", "rx_bytes", ..., "duration_sec",
        "duration_nsec"}, ...]} (yalnızca veri portları)."""
        dpid = payload["dpid"]
        now = payload.get("timestamp", time.monotonic())
        baseline_ports = 0
        for stat in sorted(payload["ports"], key=lambda s: s["port_no"]):
            metrics = self._process_port(dpid, now, stat)
            if metrics is None:
                baseline_ports += 1
                continue
            self._log_metric(metrics)
            self.bus.publish(PORT_METRICS, metrics)
        if baseline_ports:
            self.logger.info("[MONITORING] METRIC_BASELINE dpid=%016x "
                             "ports=%d (rates available from next poll)",
                             dpid, baseline_ports)

    def _process_port(self, dpid, now, stat):
        """Bir portun örneğini işler. Önceki örnek yoksa veya sayaçlar
        sıfırlandıysa baseline kaydeder ve None döner; aksi halde metrik
        dict'i döner."""
        key = (dpid, stat["port_no"])
        counters = dict((name, self._counter(stat.get(name)))
                        for name in _ALL_COUNTERS)
        # Zaman: switch'in port süresi (duration) daha hassastır; yoksa
        # cevabın controller'a ulaştığı monotonic zaman kullanılır.
        duration = None
        if stat.get("duration_sec") is not None:
            duration = (stat["duration_sec"] +
                        stat.get("duration_nsec", 0) / 1e9)

        prev = self._prev_samples.get(key)
        sample = {"t": now, "duration": duration}
        for name in _RATE_COUNTERS:
            sample[name] = counters[name]
        self._prev_samples[key] = sample

        if prev is None:
            return None

        dt = None
        if duration is not None and prev["duration"] is not None:
            dt = duration - prev["duration"]
        if dt is None or dt <= 0:
            dt = now - prev["t"]
        if dt <= 0:
            return None

        deltas = {}
        for name in _RATE_COUNTERS:
            cur, old = counters[name], prev[name]
            if cur is None or old is None:
                deltas[name] = None
            elif cur < old:
                # Sayaç sıfırlandı (port/switch yeniden oluşturuldu):
                # bu örnek yeni baseline olur
                return None
            else:
                deltas[name] = cur - old

        def rate(name):
            d = deltas[name]
            return None if d is None else d / dt

        rx_bps = rate("rx_bytes")
        tx_bps = rate("tx_bytes")
        rx_pps = rate("rx_packets")
        tx_pps = rate("tx_packets")
        rx_mbps = None if rx_bps is None else rx_bps * 8 / 1e6
        tx_mbps = None if tx_bps is None else tx_bps * 8 / 1e6
        # Throughput tahmini: portun iki yöndeki toplam bit hızı
        throughput = None
        if rx_mbps is not None and tx_mbps is not None:
            throughput = rx_mbps + tx_mbps
        packet_rate = None
        if rx_pps is not None and tx_pps is not None:
            packet_rate = rx_pps + tx_pps

        status = self._port_status.get(key, {})
        metrics = {"dpid": dpid, "port_no": stat["port_no"],
                   "name": status.get("name"),
                   "link_up": status.get("link_up"),
                   "admin_up": status.get("admin_up"),
                   "interval_sec": dt,
                   "rx_bytes_per_sec": rx_bps,
                   "tx_bytes_per_sec": tx_bps,
                   "rx_mbps": rx_mbps, "tx_mbps": tx_mbps,
                   "throughput_mbps": throughput,
                   "rx_pps": rx_pps, "tx_pps": tx_pps,
                   "packet_rate": packet_rate}
        metrics.update(counters)
        return metrics

    @staticmethod
    def _counter(value):
        if value is None or value == _UNSUPPORTED_COUNTER:
            return None
        return value

    @staticmethod
    def _fmt(value, spec):
        return "n/a" if value is None else spec % value

    def _log_metric(self, m):
        if m["link_up"] is None:
            status = "UNKNOWN"
        elif m["link_up"] and m["admin_up"] is not False:
            status = "UP"
        else:
            status = "DOWN"
        f = self._fmt
        self.logger.info(
            "[MONITORING] METRIC dpid=%016x port=%s name=%s status=%s "
            "rx_mbps=%s tx_mbps=%s throughput_mbps=%s pkt_rate=%s "
            "rx_packets=%s tx_packets=%s rx_errors=%s tx_errors=%s "
            "rx_dropped=%s tx_dropped=%s",
            m["dpid"], m["port_no"], m["name"] or "-", status,
            f(m["rx_mbps"], "%.3f"), f(m["tx_mbps"], "%.3f"),
            f(m["throughput_mbps"], "%.3f"), f(m["packet_rate"], "%.1f"),
            f(m["rx_packets"], "%d"), f(m["tx_packets"], "%d"),
            f(m["rx_errors"], "%d"), f(m["tx_errors"], "%d"),
            f(m["rx_dropped"], "%d"), f(m["tx_dropped"], "%d"))
