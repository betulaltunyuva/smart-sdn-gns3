"""
Smart SDN (GNS3) - Aşama 7: dashboard için salt okunur runtime durum çıktısı

Controller process'i içinde çalışır ve sistemin anlık durumunu periyodik
olarak runtime/state.json dosyasına ATOMİK olarak yazar (geçici dosya +
os.replace). Dashboard ayrı bir process'tir ve yalnızca bu dosyayı okur;
controller Python objelerine erişmez.

Yalnızca GÖZLEMCİDİR:
  - Agent metodlarını çağırmaz, agent durumunu DEĞİŞTİRMEZ; agentların iç
    durumunu (ör. RecoveryAgent._sessions) yalnızca okuyarak kopyalar.
  - EventBus'a agentlardan SONRA abone olur (FIFO teslim: agentlar her
    eventi önce alır). Kendi callback'leri exception fırlatmaz.
  - Controller logger'ına bir logging.Handler ekler; agentların mevcut
    [MONITORING]/[FAILURE]/[ROUTING]/[RECOVERY] log satırlarını olay
    günlüğü için yakalar (mevcut log çıktısı değişmez).
  - Flow kurmaz, OpenFlow mesajı göndermez, graph'ı değiştirmez.

Yazma işlemi controller'ın hub (eventlet) thread'inde yapılır; tek bir
snapshot sırasında yield edilmediğinden okunan durum tutarlıdır.
"""

import collections
import json
import logging
import os
import re
import tempfile
import time

from utils.event_bus import (LINK_FAILURE, LINK_UP, PORT_METRICS,
                             PORT_STATUS_UPDATE, PORT_HEALTH_CHANGED,
                             RECOVERY_REQUEST, TOPO_SWITCH_REMOVED)

SCHEMA_VERSION = 1
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_STATE_PATH = os.path.join(_PROJECT_ROOT, "runtime", "state.json")
WRITE_INTERVAL = 1.0          # saniye
MAX_EVENTS = 300              # bellekte tutulan son olay sayısı
STATE_EVENTS = 200            # state.json'a yazılan son olay sayısı
HISTORY_LEN = 60              # port başına metrik geçmişi (5 sn x 60 = 5 dk)
MAX_INCIDENTS = 20

_AGENT_PREFIXES = (("[MONITORING]", "MONITORING"), ("[FAILURE]", "FAILURE"),
                   ("[ROUTING]", "ROUTING"), ("[RECOVERY]", "RECOVERY"))
# Controller'ın kendi önemli log satırları -> olay adı
_CONTROLLER_EVENTS = (("SWITCH_ADDED", "SWITCH_ADDED"),
                      ("SWITCH_REMOVED", "SWITCH_REMOVED"),
                      ("LINK_ADDED", "LINK_ADDED"),
                      ("LINK_REMOVED", "LINK_REMOVED"),
                      ("NO_PATH", "NO_PATH"),
                      ("Switch bağlandı", "SWITCH_CONNECTED"),
                      ("Flood tree güncellendi", "FLOOD_TREE_UPDATED"),
                      ("SDN Controller başlatıldı", "CONTROLLER_STARTED"))
# Port başına 5 sn'de bir üretilen satırlar olay günlüğünü boğmasın
_NOISY_PREFIXES = ("[MONITORING] METRIC ",)

_LINK_RE = re.compile(r"src_dpid=([0-9a-f]+) src_port=(\S+) "
                      r"dst_dpid=([0-9a-f]+) dst_port=(\S+)")
_PORT_RE = re.compile(r"dpid=([0-9a-f]+) port=(\S+)")
_LINK_FIELD_RE = re.compile(r"link=(\S+)")
_REASON_RE = re.compile(r"reason=(\S+)")
_HOP_RE = re.compile(r"hop_count=(\d+)")
_PATH_RE = re.compile(r"path=\[([^\]]*)\]")

# Incident durumları (dashboard'da gösterilir)
FINAL_STATES = ("RESTORED", "LINK_RESTORED", "NO_PATH", "HOST_PORT",
                "INVALIDATED")


def _hex(dpid):
    return "%016x" % dpid if isinstance(dpid, int) else str(dpid)


def _port(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def link_id(a, pa, b, pb):
    """RecoveryAgent._fmt_link ile aynı biçim: uçlar (dpid, port) sıralı."""
    (a, pa), (b, pb) = sorted(((a, _port(pa)), (b, _port(pb))))
    return "%s:%s<->%s:%s" % (_hex(a), pa, _hex(b), pb)


def _link_id_from_dict(link):
    return link_id(link["src_dpid"], link["src_port"],
                   link["dst_dpid"], link["dst_port"])


def _link_id_from_key(key):
    """frozenset({(dpid, port), (dpid, port)}) -> link id."""
    (a, pa), (b, pb) = sorted(key)
    return link_id(a, pa, b, pb)


def _num(value):
    """JSON için güvenli sayı (None / NaN / inf -> None)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


class _EventLogHandler(logging.Handler):
    """Controller logger'ından olay günlüğü için kayıt yakalar."""

    def __init__(self, sink):
        super(_EventLogHandler, self).__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record):
        try:
            self._sink(record)
        except Exception:
            # Gözlemci hatası asla log/controller akışını bozmamalı
            pass


class RuntimeStateWriter(object):
    """Controller'ı gözlemleyip runtime/state.json yazar."""

    def __init__(self, controller, path=None, interval=WRITE_INTERVAL):
        self.ctl = controller
        self.path = (path or os.environ.get("SDN_STATE_PATH")
                     or DEFAULT_STATE_PATH)
        self.interval = interval
        self.started = time.time()
        self.events = collections.deque(maxlen=MAX_EVENTS)
        self.event_counts = collections.Counter()
        self.agent_last = {}          # kaynak -> son olay
        self.metric_lines = 0         # yakalanmayan METRIC satırı sayısı
        self._seq = 0
        # Metrikler: {(dpid, port_no): {...}} ve geçmiş
        self.metrics = {}
        self.history = {}
        self.port_desc = {}
        self._prev_bad = {}
        self.last_metrics_at = None
        # Arızalı linkler: {link_id: {..., "since": t}}
        self.failed_links = {}
        self.latest_route = None
        self.incidents = collections.deque(maxlen=MAX_INCIDENTS)
        self._incident_seq = 0
        self.write_count = 0
        self.write_error = None

        bus = controller.event_bus
        for event, callback in (
                (PORT_STATUS_UPDATE, self._on_port_status),
                (PORT_METRICS, self._on_port_metrics),
                (LINK_FAILURE, self._on_link_failure),
                (LINK_UP, self._on_link_up),
                (RECOVERY_REQUEST, self._on_recovery_request),
                (TOPO_SWITCH_REMOVED, self._on_switch_removed)):
            bus.subscribe(event, self._guard(callback))
        # PORT_HEALTH_CHANGED yalnızca failure agent'ın iç durumundan okunur
        self._log_handler = _EventLogHandler(self._on_log_record)
        controller.logger.addHandler(self._log_handler)

    @staticmethod
    def _guard(callback):
        def safe(payload):
            try:
                callback(payload)
            except Exception:
                pass
        safe.__name__ = "runtime_state_%s" % callback.__name__
        return safe

    # ------------------------------------------------------------------
    # EventBus gözlemcileri (yalnızca kendi kopyalarını günceller)
    # ------------------------------------------------------------------
    def _on_port_status(self, payload):
        dpid = payload["dpid"]
        for p in payload.get("ports", ()):
            self.port_desc[(dpid, p["port_no"])] = {
                "name": p.get("name"), "link_up": p.get("link_up"),
                "admin_up": p.get("admin_up")}

    def _on_port_metrics(self, m):
        now = time.time()
        key = (m["dpid"], m["port_no"])
        # Aralık başına drop / error oranı (kümülatif sayaç farkı)
        cur = dict((k, m.get(k)) for k in (
            "rx_packets", "tx_packets", "rx_dropped", "tx_dropped",
            "rx_errors", "tx_errors"))
        prev = self._prev_bad.get(key)
        self._prev_bad[key] = cur
        drop_delta = err_delta = pkt_delta = None
        if prev is not None:
            def delta(name):
                if cur[name] is None or prev[name] is None:
                    return 0
                return max(0, cur[name] - prev[name])
            pkt_delta = delta("rx_packets") + delta("tx_packets")
            drop_delta = delta("rx_dropped") + delta("tx_dropped")
            err_delta = delta("rx_errors") + delta("tx_errors")

        def ratio(bad):
            if bad is None:
                return None
            total = pkt_delta + bad
            return (float(bad) / total) if total else 0.0

        entry = {"dpid": _hex(m["dpid"]), "port_no": m["port_no"],
                 "name": m.get("name"), "link_up": m.get("link_up"),
                 "admin_up": m.get("admin_up"), "updated": now,
                 "interval_sec": _num(m.get("interval_sec")),
                 "drop_delta": drop_delta, "error_delta": err_delta,
                 "drop_ratio": ratio(drop_delta),
                 "error_ratio": ratio(err_delta)}
        for name in ("rx_mbps", "tx_mbps", "throughput_mbps", "rx_pps",
                     "tx_pps", "packet_rate"):
            entry[name] = _num(m.get(name))
        for name in ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
                     "rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
            entry[name] = m.get(name)
        self.metrics[key] = entry
        hist = self.history.setdefault(
            key, collections.deque(maxlen=HISTORY_LEN))
        hist.append([round(now, 3), entry["throughput_mbps"],
                     entry["packet_rate"]])
        self.last_metrics_at = now

    def _on_link_failure(self, link):
        # Kopmuş switch'lerin link silmeleri arıza sayılmaz (switch zaten yok)
        dps = self.ctl.datapaths
        if link["src_dpid"] not in dps or link["dst_dpid"] not in dps:
            return
        lid = _link_id_from_dict(link)
        self.failed_links[lid] = {
            "id": lid, "a": _hex(link["src_dpid"]), "a_port": link["src_port"],
            "b": _hex(link["dst_dpid"]), "b_port": link["dst_port"],
            "status": "FAILED", "since": time.time()}

    def _on_link_up(self, link):
        # Incident adımı controller'ın LINK_ADDED log satırından eklenir
        # (agent zincirinden önce loglandığı için sıra doğru kalır).
        self.failed_links.pop(_link_id_from_dict(link), None)

    def _on_recovery_request(self, req):
        self.latest_route = {
            "t": time.time(), "trigger": req.get("trigger"),
            "reason": req.get("reason"),
            "src": _hex(req.get("src_dpid")), "dst": _hex(req.get("dst_dpid")),
            "path": [_hex(d) for d in req.get("path") or []],
            "hop_count": req.get("hop_count"),
            "excluded_edges": len(req.get("excluded_edges") or []),
            "affected_link": (_link_id_from_dict(req["affected_link"])
                              if req.get("affected_link") else None)}

    def _on_switch_removed(self, payload):
        dpid = payload["dpid"]
        h = _hex(dpid)
        for store in (self.metrics, self.history, self.port_desc,
                      self._prev_bad):
            for key in [k for k in store if k[0] == dpid]:
                del store[key]
        for lid in [l for l, v in self.failed_links.items()
                    if h in (v["a"], v["b"])]:
            del self.failed_links[lid]

    # ------------------------------------------------------------------
    # Log yakalama: olay günlüğü + self-healing incident zaman çizelgesi
    # ------------------------------------------------------------------
    def _on_log_record(self, record):
        msg = record.getMessage()
        if msg.startswith(_NOISY_PREFIXES):
            self.metric_lines += 1
            return
        source = event = None
        body = msg
        for prefix, name in _AGENT_PREFIXES:
            if msg.startswith(prefix):
                source = name
                body = msg[len(prefix):].strip()
                event = body.split(" ", 1)[0]
                break
        else:
            for needle, name in _CONTROLLER_EVENTS:
                if msg.startswith(needle):
                    source, event = "CONTROLLER", name
                    break
        if source is None:
            return
        self._seq += 1
        ev = {"seq": self._seq, "t": record.created,
              "level": record.levelname, "source": source, "event": event,
              "message": body[:400]}
        self.events.append(ev)
        self.event_counts["%s.%s" % (source, event)] += 1
        self.agent_last[source] = ev
        self._track_incident(source, event, body, record.created)

    def _new_incident(self, kind, lid, t, detail, port=None):
        self._incident_seq += 1
        inc = {"id": self._incident_seq, "kind": kind, "link": lid,
               "port": port, "started": t, "status": "DETECTED",
               "reason": "link_down" if kind == "LINK_FAILURE" else "metrics",
               "recovery_ms": None, "route": None, "steps": []}
        self._add_step(inc, "DETECTED", t, detail)
        self.incidents.append(inc)
        return inc

    @staticmethod
    def _add_step(inc, step, t, detail):
        inc["steps"].append({"step": step, "t": t,
                             "dt_ms": round((t - inc["started"]) * 1000, 1),
                             "detail": detail[:240]})
        del inc["steps"][:-25]

    def _find_incident(self, lid, active_only=False):
        for inc in reversed(self.incidents):
            if inc["link"] != lid:
                continue
            if active_only and inc["status"] in FINAL_STATES:
                return None
            return inc
        return None

    def _current_incident(self, t):
        """Senkron agent zinciri içindeki satırlar en son incident'e aittir
        (zincir tek handler çağrısında, birkaç ms içinde tamamlanır)."""
        if self.incidents and t - self.incidents[-1]["started"] < 5.0:
            return self.incidents[-1]
        return None

    def _isl_link_for_port(self, dpid, port_no):
        topo = getattr(self.ctl, "topology", None)
        if topo is None or not topo.graph.has_node(dpid):
            return None
        for nbr in topo.graph.adj[dpid]:
            ports = topo.graph.edges[dpid, nbr]["ports"]
            if ports.get(dpid) == port_no:
                return link_id(dpid, port_no, nbr, ports[nbr])
        return None

    def _track_incident(self, source, event, body, t):
        if source == "MONITORING" and event == "LINK_DOWN":
            m = _LINK_RE.search(body)
            if m:
                lid = link_id(int(m.group(1), 16), m.group(2),
                              int(m.group(3), 16), m.group(4))
                self._new_incident("LINK_FAILURE", lid, t, body)
            return
        if source == "FAILURE" and event == "PORT_DEGRADED":
            m = _PORT_RE.search(body)
            if m:
                dpid, port_no = int(m.group(1), 16), _port(m.group(2))
                lid = self._isl_link_for_port(dpid, port_no)
                inc = (self._find_incident(lid, active_only=True)
                       if lid else None)
                if inc is not None:
                    # Linkin diğer ucu da DEGRADED: aynı incident
                    self._add_step(inc, "DEGRADED_OTHER_END", t, body)
                else:
                    self._new_incident("PORT_DEGRADED", lid, t, body,
                                       port="%s:%s" % (_hex(dpid), port_no))
            return
        if source == "CONTROLLER" and event == "LINK_ADDED":
            m = _LINK_RE.search(body)
            lid = (link_id(int(m.group(1), 16), m.group(2),
                           int(m.group(3), 16), m.group(4)) if m else None)
            inc = self._find_incident(lid, active_only=True) if lid else None
            if inc is not None and inc["kind"] == "LINK_FAILURE":
                self._add_step(inc, "LINK_UP", t, body)
                if inc["status"] not in ("RECOVERED", "FAILBACK_PENDING"):
                    inc["status"] = "LINK_RESTORED"
            return
        if source == "FAILURE" and event == "PORT_RECOVERED":
            m = _PORT_RE.search(body)
            lid = (self._isl_link_for_port(int(m.group(1), 16),
                                           _port(m.group(2))) if m else None)
            inc = self._find_incident(lid, active_only=True) if lid else None
            if inc is not None and inc["kind"] == "PORT_DEGRADED":
                self._add_step(inc, "PORT_RECOVERED", t, body)
                if inc["status"] not in ("RECOVERED", "FAILBACK_PENDING"):
                    inc["status"] = "LINK_RESTORED"
            return

        # Asenkron (sonradan gelen) recovery satırları link= ile eşleşir
        lf = _LINK_FIELD_RE.search(body)
        if source == "RECOVERY" and event in (
                "FAILBACK_PENDING", "FAILBACK_CANCELLED", "FAILBACK_START",
                "FAILBACK_COMPLETE", "SESSION_INVALIDATED",
                "SESSION_SUPERSEDED") and lf:
            inc = self._find_incident(lf.group(1))
            if inc is None:
                return
            self._add_step(inc, event, t, body)
            inc["status"] = {
                "FAILBACK_PENDING": "FAILBACK_PENDING",
                "FAILBACK_CANCELLED": "RECOVERED",
                "FAILBACK_START": "FAILBACK_PENDING",
                "FAILBACK_COMPLETE": "RESTORED",
                "SESSION_INVALIDATED": "INVALIDATED",
                "SESSION_SUPERSEDED": "INVALIDATED"}[event]
            return

        inc = self._current_incident(t)
        if inc is None:
            return
        if source == "FAILURE" and event == "LINK_FAILURE":
            self._add_step(inc, "CONFIRMED", t, body)
        elif source == "ROUTING" and event == "ALTERNATIVE_PATH":
            hop, path = _HOP_RE.search(body), _PATH_RE.search(body)
            inc["route"] = {
                "hop_count": int(hop.group(1)) if hop else None,
                "path": ([p.strip() for p in path.group(1).split(",")
                          if p.strip()] if path else [])}
            inc["status"] = "ROUTED"
            self._add_step(inc, "ROUTE_SELECTED", t, body)
        elif source == "ROUTING" and event == "NO_ALTERNATIVE_PATH":
            r = _REASON_RE.search(body)
            inc["status"] = "NO_PATH"
            inc["outcome_reason"] = r.group(1) if r else None
            self._add_step(inc, "NO_ALTERNATIVE_PATH", t, body)
        elif source == "ROUTING" and event == "DEGRADED_HOST_PORT":
            inc["status"] = "HOST_PORT"
            self._add_step(inc, "HOST_PORT_IGNORED", t, body)
        elif source == "RECOVERY" and event == "FLOW_INSTALL_START":
            self._add_step(inc, "FLOW_INSTALL_START", t, body)
        elif source == "RECOVERY" and event == "PATH_ACTIVE":
            if inc["status"] != "RECOVERED":
                inc["status"] = "RECOVERED"
                inc["recovery_ms"] = round((t - inc["started"]) * 1000, 1)
                self._add_step(inc, "PATH_ACTIVE", t, body)
        elif source == "RECOVERY" and event == "FLOW_INSTALL_FAILED":
            inc["status"] = "INSTALL_FAILED"
            self._add_step(inc, "FLOW_INSTALL_FAILED", t, body)
        elif (source == "RECOVERY" and event == "SKIPPED"
              and body.startswith("SKIPPED trigger=")):
            r = _REASON_RE.search(body)
            inc["status"] = "SKIPPED"
            inc["outcome_reason"] = r.group(1) if r else None
            self._add_step(inc, "RECOVERY_SKIPPED", t, body)
        elif source == "RECOVERY" and event == "DUPLICATE_REQUEST":
            inc["status"] = "DUPLICATE"
            self._add_step(inc, "DUPLICATE_REQUEST", t, body)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self):
        now = time.time()
        state = {"schema": SCHEMA_VERSION, "timestamp": now}
        sections = (("controller", self._controller_section),
                    ("switches", self._switches_section),
                    ("links", self._links_section),
                    ("topology", self._topology_section),
                    ("metrics", self._metrics_section),
                    ("agents", self._agents_section),
                    ("recovery", self._recovery_section))
        for name, build in sections:
            try:
                state[name] = build()
            except Exception as e:      # bir bölüm hatası diğerlerini bozmasın
                state[name] = {"error": "%s: %s" % (type(e).__name__, e)}
        state["failed_links"] = list(self._live_failed_links())
        state["latest_route"] = self.latest_route
        state["incidents"] = [dict(i) for i in self.incidents]
        state["latest_failure"] = (dict(self.incidents[-1])
                                   if self.incidents else None)
        state["events"] = list(self.events)[-STATE_EVENTS:]
        state["event_counts"] = dict(self.event_counts)
        return state

    def _live_failed_links(self):
        dps = set(_hex(d) for d in self.ctl.datapaths)
        for v in self.failed_links.values():
            if v["a"] in dps and v["b"] in dps:
                yield v

    def _controller_section(self):
        conf = getattr(self.ctl, "CONF", None)
        return {"status": "ONLINE", "pid": os.getpid(),
                "started": self.started,
                "uptime_sec": round(time.time() - self.started, 1),
                "openflow": "1.3",
                "observe_links": bool(getattr(conf, "observe_links", False)),
                "topology_enabled": getattr(self.ctl, "topology", None)
                is not None,
                "stats_interval": getattr(self.ctl, "STATS_INTERVAL", None),
                "state_interval": self.interval,
                "metric_log_lines": self.metric_lines,
                "write_count": self.write_count}

    def _port_health(self):
        agent = getattr(self.ctl, "failure_agent", None)
        ports = getattr(agent, "_ports", None) or {}
        return dict((k, {"state": v.get("state"), "reason": v.get("reason")})
                    for k, v in list(ports.items()))

    def _switches_section(self):
        health = self._port_health()
        isl = getattr(self.ctl, "isl_ports", {}) or {}
        tree = getattr(self.ctl, "tree_ports", {}) or {}
        macs = getattr(self.ctl, "mac_to_port", {}) or {}
        result = []
        for dpid, dp in sorted(self.ctl.datapaths.items()):
            addr = getattr(dp, "address", None) or (None, None)
            port_nos = sorted(set(p for (d, p) in self.port_desc if d == dpid)
                              | set(p for (d, p) in health if d == dpid))
            states = [health.get((dpid, p), {}).get("state") for p in port_nos]
            if "FAILED" in states:
                worst = "FAILED"
            elif "DEGRADED" in states:
                worst = "DEGRADED"
            else:
                worst = "HEALTHY"
            ports = []
            for p in port_nos:
                desc = self.port_desc.get((dpid, p), {})
                h = health.get((dpid, p), {})
                ports.append({"port_no": p, "name": desc.get("name"),
                              "link_up": desc.get("link_up"),
                              "admin_up": desc.get("admin_up"),
                              "health": h.get("state"),
                              "health_reason": h.get("reason"),
                              "is_isl": p in isl.get(dpid, ()),
                              "in_flood_tree": p in tree.get(dpid, ())})
            result.append({
                "dpid": _hex(dpid), "dpid_int": dpid,
                "address": addr[0] if len(addr) > 0 else None,
                "tcp_port": addr[1] if len(addr) > 1 else None,
                "connected": True, "health": worst,
                "port_count": len(port_nos),
                "isl_ports": sorted(isl.get(dpid, ())),
                "learned_macs": len(macs.get(dpid, {})),
                "ports": ports})
        return result

    def _degraded_links(self):
        agent = getattr(self.ctl, "routing_agent", None)
        degraded = getattr(agent, "_degraded", None) or {}
        return dict((_link_id_from_key(k),
                     ["%s:%s" % (_hex(d), p) for d, p in sorted(v)])
                    for k, v in list(degraded.items()))

    def _links_section(self):
        degraded = self._degraded_links()
        tree = getattr(self.ctl, "tree_ports", {}) or {}
        result = []
        for info in list(self.ctl.links.values()):
            a, pa = info["src_dpid"], info["src_port"]
            b, pb = info["dst_dpid"], info["dst_port"]
            lid = link_id(a, pa, b, pb)
            result.append({
                "id": lid, "a": _hex(a), "a_port": pa, "b": _hex(b),
                "b_port": pb,
                "status": "DEGRADED" if lid in degraded else "UP",
                "degraded_by": degraded.get(lid, []),
                "in_flood_tree": (pa in tree.get(a, ()) and
                                  pb in tree.get(b, ()))})
        return sorted(result, key=lambda l: l["id"])

    def _topology_section(self):
        topo = getattr(self.ctl, "topology", None)
        if topo is None:
            return {"enabled": False}
        g = topo.graph
        try:
            import networkx as nx
            components = nx.number_connected_components(g) if len(g) else 0
        except Exception:
            components = None
        return {"enabled": True,
                "nodes": sorted(_hex(n) for n in g.nodes),
                "edges": sorted(sorted((_hex(u), _hex(v))) for u, v in g.edges),
                "node_count": g.number_of_nodes(),
                "edge_count": g.number_of_edges(),
                "components": components}

    def _metrics_section(self):
        health = self._port_health()
        isl = getattr(self.ctl, "isl_ports", {}) or {}
        ports = []
        for (dpid, p), m in sorted(self.metrics.items()):
            e = dict(m)
            h = health.get((dpid, p), {})
            e["health"], e["health_reason"] = h.get("state"), h.get("reason")
            e["is_isl"] = p in isl.get(dpid, ())
            ports.append(e)
        history = dict(("%s:%s" % (_hex(d), p), list(h))
                       for (d, p), h in self.history.items())
        return {"updated": self.last_metrics_at, "ports": ports,
                "history": history}

    def _agents_section(self):
        ctl = self.ctl
        now = time.time()
        mon = getattr(ctl, "monitoring_agent", None)
        health = self._port_health()
        counts = collections.Counter(v["state"] for v in health.values())
        unhealthy = [{"dpid": _hex(d), "port_no": p, "state": v["state"],
                      "reason": v["reason"]}
                     for (d, p), v in sorted(health.items())
                     if v["state"] != "HEALTHY"]
        rec = getattr(ctl, "recovery_agent", None)
        sessions = getattr(rec, "_sessions", None) or {}
        stats_interval = getattr(ctl, "STATS_INTERVAL", 5) or 5
        if self.last_metrics_at is None:
            mon_status = "WAITING"
        elif now - self.last_metrics_at > 3 * stats_interval:
            mon_status = "STALE"
        else:
            mon_status = "RUNNING"
        return {
            "monitoring": {
                "status": mon_status,
                "ports_tracked": len(getattr(mon, "_port_status", {}) or {}),
                "rate_samples": len(getattr(mon, "_prev_samples", {}) or {}),
                "last_metrics_at": self.last_metrics_at,
                "metric_count": self.metric_lines,
                "last_event": self.agent_last.get("MONITORING")},
            "failure": {
                "status": ("ALERT" if counts.get("FAILED") or
                           counts.get("DEGRADED") else "RUNNING"),
                "healthy": counts.get("HEALTHY", 0),
                "degraded": counts.get("DEGRADED", 0),
                "failed": counts.get("FAILED", 0),
                "unhealthy_ports": unhealthy,
                "last_event": self.agent_last.get("FAILURE")},
            "routing": {
                "status": ("ENABLED" if getattr(ctl, "topology", None)
                           is not None else "DISABLED"),
                "degraded_links": self._degraded_links(),
                "decisions": self.event_counts.get(
                    "ROUTING.ALTERNATIVE_PATH", 0),
                "no_path": self.event_counts.get(
                    "ROUTING.NO_ALTERNATIVE_PATH", 0),
                "last_decision": self.latest_route,
                "last_event": self.agent_last.get("ROUTING")},
            "recovery": {
                "status": "ACTIVE" if sessions else "IDLE",
                "active_sessions": len(sessions),
                "failback_pending": sum(1 for s in list(sessions.values())
                                        if s.get("failback_at") is not None),
                "known_hosts": len(getattr(rec, "_hosts", {}) or {}),
                "paths_activated": self.event_counts.get(
                    "RECOVERY.PATH_ACTIVE", 0),
                "failbacks_completed": self.event_counts.get(
                    "RECOVERY.FAILBACK_COMPLETE", 0),
                "last_event": self.agent_last.get("RECOVERY")},
        }

    def _recovery_section(self):
        rec = getattr(self.ctl, "recovery_agent", None)
        if rec is None:
            return {"status": "DISABLED", "sessions": [], "hosts": []}
        clock = getattr(rec, "clock", time.monotonic)
        mono_now, wall_now = clock(), time.time()
        sessions = []
        for key, s in list((getattr(rec, "_sessions", None) or {}).items()):
            pairs = []
            for pair, entry in list(s.get("pairs", {}).items()):
                pairs.append({"pair": "<->".join(sorted(pair)),
                              "path": [_hex(d) for d in entry.get("path", [])],
                              "flows": len(entry.get("flows", []))})
            fb = s.get("failback_at")
            started = s.get("started")
            sessions.append({
                "link": _link_id_from_key(key),
                "trigger": s.get("trigger"), "reason": s.get("reason"),
                "routing_path": [_hex(d) for d in s.get("routing_path", [])],
                "started": (wall_now - (mono_now - started)
                            if started is not None else None),
                "state": "FAILBACK_PENDING" if fb is not None else "ACTIVE",
                "failback_in_sec": (round(max(0.0, fb - mono_now), 1)
                                    if fb is not None else None),
                "degraded_ports": ["%s:%s" % (_hex(d), p) for d, p in
                                   sorted(s.get("degraded_ports", ()))],
                "flow_count": sum(p["flows"] for p in pairs),
                "pairs": sorted(pairs, key=lambda p: p["pair"])})
        hosts = [{"mac": mac, "dpid": _hex(loc[0]), "port": loc[1]}
                 for mac, loc in sorted(list(
                     (getattr(rec, "_hosts", None) or {}).items()))]
        if any(s["state"] == "FAILBACK_PENDING" for s in sessions):
            status = "FAILBACK_PENDING"
        elif sessions:
            status = "ACTIVE"
        else:
            status = "IDLE"
        return {"status": status,
                "sessions": sorted(sessions, key=lambda s: s["link"]),
                "hosts": hosts}

    # ------------------------------------------------------------------
    # Atomik yazma
    # ------------------------------------------------------------------
    def write(self):
        data = json.dumps(self.snapshot(), separators=(",", ":"),
                          default=str, allow_nan=False)
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        # Aynı dizinde geçici dosya + os.replace: okuyucu ya eski ya da yeni
        # dosyanın TAMAMINI görür; yarım yazılmış JSON görünmez.
        fd, tmp = tempfile.mkstemp(prefix=".state.", suffix=".tmp",
                                   dir=directory)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.write_count += 1

    def run(self, sleep):
        """Controller hub thread'inde döngü: sleep = hub.sleep."""
        while True:
            try:
                self.write()
                if self.write_error is not None:
                    self.ctl.logger.info("Runtime state yazımı düzeldi: %s",
                                         self.path)
                    self.write_error = None
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
                if err != self.write_error:     # aynı hatayı tekrar loglama
                    self.ctl.logger.warning("Runtime state yazılamadı "
                                            "(dashboard verisi eski kalabilir)"
                                            ": %s", err)
                self.write_error = err
            sleep(self.interval)
