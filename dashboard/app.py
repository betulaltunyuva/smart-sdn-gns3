"""
Smart SDN (GNS3) - Aşama 7: gerçek zamanlı izleme dashboard'u (Streamlit)

Yalnızca GÖZLEMLER: controller'ın atomik olarak yazdığı runtime/state.json
dosyasını okur (dashboard/state_reader.py). Controller'a, agentlara veya
OVS ayarlarına hiçbir şey yazmaz.

Çalıştırma (proje kökünden):
    ./start_dashboard.sh
    # veya: .venv/bin/streamlit run dashboard/app.py
"""

import html
import os
import sys
import time
from datetime import datetime

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_reader as sr  # noqa: E402
import presentation as pres  # noqa: E402

REFRESH_SEC = 2

# Renk paleti (koyu tema)
C = {"bg": "#0b1120", "card": "#111a2e", "border": "#1f2b46",
     "text": "#e2e8f0", "muted": "#8b9bb8", "cyan": "#22d3ee",
     "green": "#34d399", "amber": "#fbbf24", "red": "#f87171",
     "violet": "#a78bfa", "blue": "#60a5fa", "slate": "#64748b"}

STATUS_TONE = {
    "ONLINE": "ok", "RUNNING": "ok", "ENABLED": "ok", "HEALTHY": "ok",
    "RECOVERED": "ok", "RESTORED": "ok", "LINK_RESTORED": "ok", "UP": "ok",
    "IDLE": "muted", "SKIPPED": "muted", "DUPLICATE": "muted",
    "HOST_PORT": "muted", "INVALIDATED": "muted",
    "ACTIVE": "info", "ROUTED": "violet",
    "WAITING": "warn", "STALE": "warn", "DEGRADED": "warn",
    "DETECTED": "warn", "FAILBACK_PENDING": "warn",
    "ALERT": "err", "OFFLINE": "err", "FAILED": "err", "NO_PATH": "err",
    "INSTALL_FAILED": "err", "DISABLED": "err", "DOWN": "err",
}
SOURCE_COLOR = {"MONITORING": C["cyan"], "FAILURE": C["red"],
                "ROUTING": C["violet"], "RECOVERY": C["green"],
                "CONTROLLER": C["blue"]}
REASON_TEXT = {
    "insufficient_forwarding_context":
        "Bilinen host konumu yetersiz (iki farklı switch'te host trafiği "
        "görülmedi). Learning switch trafiği yeni topolojide yeniden öğrenir.",
    "no_affected_host_traffic":
        "Arızalı linki kullanan bilinen host trafiği yok; recovery flow'u "
        "gerekmedi.",
    "disconnected": "Kalan topolojide iki uç arasında yol yok.",
    "execution_disabled": "Recovery yürütmesi devre dışı (topology/flow_ops yok).",
    "invalid_request": "Routing isteği doğrulamadan geçmedi.",
    "dpid_not_in_graph": "Switch graph'ta değil.",
    "topology_disabled": "NetworkX yok; topoloji graph'ı kapalı.",
}

CSS = """
<style>
:root { --bg:%(bg)s; --card:%(card)s; --border:%(border)s; --text:%(text)s;
        --muted:%(muted)s; --cyan:%(cyan)s; --green:%(green)s;
        --amber:%(amber)s; --red:%(red)s; --violet:%(violet)s;
        --blue:%(blue)s; }
.stApp { background: radial-gradient(1200px 600px at 10%% -10%%,
         #12203d 0%%, var(--bg) 55%%) fixed; color: var(--text); }
.block-container { padding-top: 1.4rem; padding-bottom: 2rem;
                   max-width: 1600px; }
header[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, h4 { color: var(--text); letter-spacing: .2px; }
.hdr { display:flex; justify-content:space-between; align-items:flex-end;
       flex-wrap:wrap; gap:12px; margin-bottom: 14px; }
.hdr-title { font-size: 1.75rem; font-weight: 750; line-height: 1.15; }
.hdr-title span { color: var(--cyan); }
.hdr-sub { color: var(--muted); font-size: .9rem; margin-top: 4px; }
.hdr-right { color: var(--muted); font-size: .85rem; text-align:right; }
.live-dot { display:inline-block; width:9px; height:9px; border-radius:50%%;
            background: var(--green); margin-right:6px;
            box-shadow: 0 0 0 0 rgba(52,211,153,.7);
            animation: pulse 1.8s infinite; }
.live-dot.off { background: var(--red); animation:none; }
.live-dot.paused { background: var(--amber); animation:none; }
@keyframes pulse { 0%% { box-shadow: 0 0 0 0 rgba(52,211,153,.6); }
  70%% { box-shadow: 0 0 0 9px rgba(52,211,153,0); }
  100%% { box-shadow: 0 0 0 0 rgba(52,211,153,0); } }
.section { font-size: 1.05rem; font-weight: 700; margin: 22px 0 10px 0;
           display:flex; align-items:center; gap:8px; }
.section:before { content:""; width:4px; height:18px; border-radius:2px;
                  background: linear-gradient(var(--cyan), var(--violet)); }
.grid { display:grid; gap:12px; }
.kpi-grid { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
.agent-grid { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.card { background: linear-gradient(180deg, rgba(255,255,255,.025),
        rgba(255,255,255,0)) , var(--card);
        border: 1px solid var(--border); border-radius: 14px;
        padding: 14px 16px; position: relative; overflow: hidden; }
.kpi .label { color: var(--muted); font-size: .74rem; font-weight: 600;
              text-transform: uppercase; letter-spacing: .08em; }
.kpi .value { font-size: 1.75rem; font-weight: 750; margin-top: 4px;
              line-height: 1.1; }
.kpi .sub { color: var(--muted); font-size: .8rem; margin-top: 6px; }
.kpi:after { content:""; position:absolute; left:0; top:0; bottom:0;
             width:3px; background: var(--tone, var(--slate)); }
.tone-ok { --tone: var(--green); } .tone-warn { --tone: var(--amber); }
.tone-err { --tone: var(--red); } .tone-info { --tone: var(--cyan); }
.tone-violet { --tone: var(--violet); } .tone-muted { --tone: #64748b; }
.v-ok { color: var(--green); } .v-warn { color: var(--amber); }
.v-err { color: var(--red); } .v-info { color: var(--cyan); }
.v-violet { color: var(--violet); } .v-muted { color: #94a3b8; }
.pill { display:inline-block; padding: 2px 9px; border-radius: 999px;
        font-size: .7rem; font-weight: 700; letter-spacing: .05em;
        border: 1px solid currentColor; white-space: nowrap; }
.agent-head { display:flex; justify-content:space-between;
              align-items:center; margin-bottom: 10px; }
.agent-name { font-weight: 700; font-size: .98rem; }
.agent-name small { display:block; color: var(--muted); font-weight: 500;
                    font-size: .74rem; }
.stats { display:grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
         margin-bottom: 10px; }
.stat .n { font-size: 1.2rem; font-weight: 700; }
.stat .t { color: var(--muted); font-size: .7rem; }
.last { background: rgba(0,0,0,.22); border: 1px solid var(--border);
        border-radius: 10px; padding: 8px 10px; font-size: .78rem; }
.last .ev { font-weight: 700; }
.last .msg { color: var(--muted); font-family: ui-monospace, monospace;
             font-size: .72rem; margin-top: 3px; word-break: break-all; }
.timeline { margin-top: 6px; }
.tl-row { display:flex; gap:10px; align-items:flex-start;
          padding: 6px 0; border-left: 2px solid var(--border);
          margin-left: 6px; padding-left: 14px; position: relative; }
.tl-row:before { content:""; position:absolute; left:-7px; top:10px;
                 width:12px; height:12px; border-radius:50%%;
                 background: var(--tone, var(--slate));
                 border: 2px solid var(--card); }
.tl-step { font-weight: 700; font-size: .82rem; min-width: 170px; }
.tl-dt { color: var(--cyan); font-family: ui-monospace, monospace;
         font-size: .78rem; min-width: 80px; }
.tl-detail { color: var(--muted); font-family: ui-monospace, monospace;
             font-size: .7rem; word-break: break-all; }
.path { display:flex; flex-wrap:wrap; align-items:center; gap:6px;
        margin: 8px 0; }
.hop { background: rgba(167,139,250,.12); border: 1px solid
       rgba(167,139,250,.45); color: #ddd6fe; padding: 4px 10px;
       border-radius: 8px; font-weight: 600; font-size: .82rem; }
.arrow { color: var(--muted); }
.kv { display:grid; grid-template-columns: 150px 1fr; gap: 4px 10px;
      font-size: .84rem; }
.kv .k { color: var(--muted); }
.big-num { font-size: 2rem; font-weight: 800; color: var(--green); }
.log { max-height: 470px; overflow-y: auto; border: 1px solid var(--border);
       border-radius: 12px; background: rgba(0,0,0,.25); }
.log-row { display:grid; grid-template-columns: 92px 112px 1fr; gap: 10px;
           padding: 6px 12px; border-bottom: 1px solid rgba(31,43,70,.6);
           font-size: .78rem; align-items: baseline; }
.log-row:hover { background: rgba(34,211,238,.05); }
.log-time { color: var(--muted); font-family: ui-monospace, monospace; }
.log-src { font-weight: 700; font-size: .68rem; letter-spacing: .05em; }
.log-msg { font-family: ui-monospace, monospace; word-break: break-all; }
.log-msg b { font-family: inherit; }
.log-row.WARNING .log-msg { color: #fde68a; }
.log-row.ERROR .log-msg { color: #fca5a5; }
.banner { border-radius: 12px; padding: 10px 14px; margin: 6px 0 4px 0;
          font-size: .86rem; border: 1px solid; }
.banner.warn { background: rgba(251,191,36,.08); border-color:
               rgba(251,191,36,.4); color: #fde68a; }
.banner.err { background: rgba(248,113,113,.08); border-color:
              rgba(248,113,113,.4); color: #fecaca; }
.muted { color: var(--muted); font-size: .8rem; }
.empty { color: var(--muted); font-size: .85rem; padding: 18px 4px; }
div[data-testid="stDataFrame"] { border: 1px solid var(--border);
                                 border-radius: 12px; }
</style>
""" % C


# ----------------------------------------------------------------------
# Küçük yardımcılar
# ----------------------------------------------------------------------
def esc(value):
    return html.escape("" if value is None else str(value))


def tone(status):
    return STATUS_TONE.get(str(status), "muted")


def pill(status, label=None):
    return '<span class="pill v-%s">%s</span>' % (tone(status),
                                                  esc(label or status))


def clock_time(ts, ms=False):
    if not isinstance(ts, (int, float)):
        return "-"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S") + (".%03d" % (dt.microsecond // 1000)
                                      if ms else "")


def fmt_num(value, spec="%.2f", none="-"):
    return none if not isinstance(value, (int, float)) else spec % value


def section(title):
    st.markdown('<div class="section">%s</div>' % esc(title),
                unsafe_allow_html=True)


def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


# ----------------------------------------------------------------------
# Veri
# ----------------------------------------------------------------------
@st.cache_data(ttl=15, show_spinner=False)
def cached_inventory():
    return sr.ovs_inventory()


def read_live_state():
    """Son geçerli state'i session'da tutar; okuma hatasında onu kullanır."""
    ss = st.session_state
    paused = not ss.get("opt_live", True)
    if paused and "last_state" in ss:
        return ss["last_state"], None, ss.get("last_age"), True
    state, err, age = sr.load_state()
    if state is not None:
        ss["last_state"], ss["last_age"] = state, age
        return state, None, age, False
    prev = ss.get("last_state")
    prev_age = None
    if prev is not None and isinstance(prev.get("timestamp"), (int, float)):
        prev_age = time.time() - prev["timestamp"]
    return prev, err, prev_age, False


# ----------------------------------------------------------------------
# Başlık ve KPI kartları
# ----------------------------------------------------------------------
def render_header(status, detail, age, paused):
    dot = "paused" if paused else ("" if status == "ONLINE" else "off")
    mode = "Duraklatıldı" if paused else "Canlı · %d sn" % REFRESH_SEC
    st.markdown("""
<div class="hdr">
  <div>
    <div class="hdr-title">Smart SDN <span>Self-Healing</span> Dashboard</div>
    <div class="hdr-sub">GNS3 · Open vSwitch · OpenFlow 1.3 · OS-Ken
      multi-agent (Monitoring → Failure → Routing → Recovery)</div>
  </div>
  <div class="hdr-right"><span class="live-dot %s"></span>%s<br>
    Son veri: %s · %s</div>
</div>""" % (dot, esc(mode), esc(sr.ago(time.time() - age) if age is not None
                                   else "-"), esc(detail)),
                unsafe_allow_html=True)


def kpi(label, value, sub, status):
    return ('<div class="card kpi tone-%s"><div class="label">%s</div>'
            '<div class="value v-%s">%s</div><div class="sub">%s</div></div>'
            % (tone(status), esc(label), tone(status), esc(value), sub))


def render_kpis(state, status, inventory):
    ctl = as_dict(state.get("controller"))
    switches = as_list(state.get("switches"))
    links = as_list(state.get("links"))
    failed = as_list(state.get("failed_links"))
    degraded = [l for l in links if l.get("status") == "DEGRADED"]
    agents = as_dict(state.get("agents"))
    fail_agent = as_dict(agents.get("failure"))
    recovery = as_dict(state.get("recovery"))
    sessions = as_list(recovery.get("sessions"))
    topo = as_dict(state.get("topology"))

    uptime = sr.fmt_duration(ctl.get("uptime_sec")) if status == "ONLINE" \
        else "-"
    inv_count = len([i for i in inventory if i.get("dpid")])
    sw_sub = ("Docker'da %d OVS" % inv_count if inventory else
              "OpenFlow bağlantılı switch")
    if topo.get("components") and topo.get("components") > 1:
        sw_sub += " · ⚠ %d ayrık bileşen" % topo["components"]
    tree = sum(1 for l in links if l.get("in_flood_tree"))
    active_failures = len(failed) + len(degraded)
    bad_ports = (fail_agent.get("failed") or 0) + \
        (fail_agent.get("degraded") or 0)
    rec_status = recovery.get("status", "IDLE")
    flows = sum(s.get("flow_count") or 0 for s in sessions)
    last_inc = as_dict(state.get("latest_failure"))
    rec_sub = ("%d oturum · %d recovery flow" % (len(sessions), flows)
               if sessions else
               ("Son olay: %s (%s)" % (last_inc.get("status"),
                                       sr.ago(last_inc.get("started")))
                if last_inc else "Aktif recovery yok"))

    cards = [
        kpi("Controller", status,
            "PID %s · uptime %s" % (esc(ctl.get("pid", "-")), uptime),
            status),
        kpi("Switch", len(switches), esc(sw_sub),
            "ONLINE" if switches else "WAITING"),
        kpi("Aktif link", len(links),
            "%d flood-tree · %d DEGRADED" % (tree, len(degraded)),
            "ONLINE" if links else "WAITING"),
        kpi("Aktif failure", active_failures,
            "%d FAILED link · %d DEGRADED link · %d sorunlu port"
            % (len(failed), len(degraded), bad_ports),
            "FAILED" if failed else ("DEGRADED" if active_failures or
                                     bad_ports else "HEALTHY")),
        kpi("Recovery", rec_status, esc(rec_sub), rec_status),
    ]
    st.markdown('<div class="grid kpi-grid">%s</div>' % "".join(cards),
                unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Topoloji
# ----------------------------------------------------------------------
def stable_layout(graph):
    """Node/edge kümesi değişmedikçe aynı yerleşimi döner; değişince önceki
    konumlardan başlayarak yeniden hesaplar (switchler zıplamaz)."""
    ss = st.session_state
    sig = (tuple(sorted(graph.nodes)),
           tuple(sorted(tuple(sorted(e)) for e in graph.edges)))
    cache = ss.get("topo_layout")
    if cache and cache["sig"] == sig:
        return cache["pos"]
    if graph.number_of_nodes() == 0:
        return {}
    prev = cache["pos"] if cache else {}
    init = dict((n, prev[n]) for n in graph.nodes if n in prev)
    if not init:
        init = nx.circular_layout(sorted(graph.nodes))
    if graph.number_of_nodes() <= 2:
        pos = nx.circular_layout(sorted(graph.nodes))
    else:
        pos = nx.spring_layout(graph, pos=init, seed=42,
                               iterations=60 if prev else 200,
                               k=1.6 / (graph.number_of_nodes() ** 0.5))
    pos = dict((n, (float(p[0]), float(p[1]))) for n, p in pos.items())
    ss["topo_layout"] = {"sig": sig, "pos": pos}
    return pos


def _line_trace(edges, pos, name, color, width, dash=None, opacity=1.0,
                showlegend=True):
    xs, ys = [], []
    for u, v in edges:
        if u in pos and v in pos:
            xs += [pos[u][0], pos[v][0], None]
            ys += [pos[u][1], pos[v][1], None]
    if not xs:
        return None
    return go.Scatter(x=xs, y=ys, mode="lines", name=name,
                      line=dict(color=color, width=width, dash=dash),
                      opacity=opacity, hoverinfo="skip",
                      showlegend=showlegend)


def _path_edges(path):
    return [(a, b) for a, b in zip(path, path[1:])]


def topology_figure(state, names, inventory, show_hosts, presentation=False):
    switches = dict((s["dpid"], s) for s in as_list(state.get("switches"))
                    if isinstance(s, dict) and s.get("dpid"))
    offline = dict((i["dpid"], i) for i in inventory
                   if i.get("dpid") and i["dpid"] not in switches)
    nodes = set(switches) | set(offline)
    links = [l for l in as_list(state.get("links"))
             if l.get("a") in nodes and l.get("b") in nodes]
    failed = [l for l in as_list(state.get("failed_links"))
              if l.get("a") in nodes and l.get("b") in nodes]
    recovery = as_dict(state.get("recovery"))
    sessions = as_list(recovery.get("sessions"))
    hosts = as_list(recovery.get("hosts")) if show_hosts else []

    g = nx.Graph()
    g.add_nodes_from(nodes)
    for l in links + failed:
        g.add_edge(l["a"], l["b"])
    for h in hosts:
        if h.get("dpid") in nodes:
            g.add_edge("host:" + h["mac"], h["dpid"])
    pos = stable_layout(g)

    fig = go.Figure()
    # 1) Recovery yolu (aktif oturumların host-çifti yolları): parlak alt katman
    rec_edges = set()
    for s in sessions:
        for p in as_list(s.get("pairs")):
            rec_edges |= set(tuple(sorted(e)) for e in
                             _path_edges(as_list(p.get("path"))))
    tr = _line_trace(sorted(rec_edges), pos, "Recovery yolu (aktif)",
                     C["green"], 14, opacity=0.35)
    if tr:
        fig.add_trace(tr)
    # 2) Son routing kararı (incident kapanmadıysa)
    route = as_dict(state.get("latest_route"))
    inc = as_dict(state.get("latest_failure"))
    if presentation:
        # Geçmiş rotayı güncel gibi gösterme: yalnızca link şu an gerçekten
        # arızalıysa hesaplanan alternatif gösterilir.
        route_live = route.get("affected_link") in set(
            l.get("id") for l in failed)
    else:
        route_live = inc and inc.get("status") not in (
            "RESTORED", "LINK_RESTORED", "INVALIDATED")
    if route.get("path") and not rec_edges and route_live:
        tr = _line_trace(_path_edges(route["path"]), pos,
                         "Son alternatif rota (Routing)", C["violet"], 11,
                         opacity=0.3)
        if tr:
            fig.add_trace(tr)
    # 3) Linkler
    up = [(l["a"], l["b"]) for l in links if l.get("status") != "DEGRADED"]
    deg = [(l["a"], l["b"]) for l in links if l.get("status") == "DEGRADED"]
    lw = 4 if presentation else 3
    for edges, name, color, width, dash in (
            (up, "Çalışan bağlantı" if presentation else "Aktif link",
             C["blue"], lw, None),
            (deg, "DEGRADED link", C["amber"], lw + .5, "dot"),
            ([(l["a"], l["b"]) for l in failed],
             "Kopmuş bağlantı" if presentation else "FAILED link", C["red"],
             lw + .5, "dash")):
        tr = _line_trace(edges, pos, name, color, width, dash)
        if tr:
            fig.add_trace(tr)
    if presentation and rec_edges:
        tr = _line_trace(sorted(rec_edges), pos, "Aktif kurtarma yolu",
                         C["green"], 5)
        if tr:
            fig.add_trace(tr)
    # Host bağlantıları
    host_edges = [("host:" + h["mac"], h["dpid"]) for h in hosts
                  if h.get("dpid") in nodes]
    tr = _line_trace(host_edges, pos, "Host bağlantısı", C["slate"], 1,
                     "dot", showlegend=False)
    if tr:
        fig.add_trace(tr)

    # 4) Port etiketleri ve link hover noktaları
    lx, ly, lt = [], [], []
    hx, hy, htext = [], [], []
    for l, state_name in ([(l, l.get("status", "UP")) for l in links] +
                          [(l, "FAILED") for l in failed]):
        a, b = l["a"], l["b"]
        if a not in pos or b not in pos:
            continue
        (xa, ya), (xb, yb) = pos[a], pos[b]
        for (x0, y0), (x1, y1), port in (((xa, ya), (xb, yb), l["a_port"]),
                                         ((xb, yb), (xa, ya), l["b_port"])):
            lx.append(x0 + (x1 - x0) * 0.2)
            ly.append(y0 + (y1 - y0) * 0.2)
            lt.append("p%s" % port)
        hx.append((xa + xb) / 2)
        hy.append((ya + yb) / 2)
        extra = ""
        if state_name == "FAILED":
            extra = "<br>Arıza: %s" % sr.ago(l.get("since"))
        elif l.get("degraded_by"):
            extra = "<br>DEGRADED bildiren: %s" % ", ".join(l["degraded_by"])
        htext.append("<b>%s</b><br>Durum: %s<br>Flood tree: %s%s" % (
            esc(sr.pretty_link(l.get("id"), names)), state_name,
            "evet" if l.get("in_flood_tree") else "hayır (bloklu)"
            if state_name != "FAILED" else "-", extra))
    if lx:
        fig.add_trace(go.Scatter(
            x=lx, y=ly, mode="text", text=lt, hoverinfo="skip",
            textfont=dict(size=13 if presentation else 10,
                          color=C["text"] if presentation else C["muted"]),
            showlegend=False))
    if hx:
        fig.add_trace(go.Scatter(
            x=hx, y=hy, mode="markers", hovertext=htext, hoverinfo="text",
            marker=dict(size=14, color="rgba(0,0,0,0)"), showlegend=False))

    # 5) Hostlar
    if hosts:
        pts = [h for h in hosts if "host:" + h["mac"] in pos]
        fig.add_trace(go.Scatter(
            x=[pos["host:" + h["mac"]][0] for h in pts],
            y=[pos["host:" + h["mac"]][1] for h in pts],
            mode="markers+text", name="Host",
            text=[h["mac"][-8:] for h in pts], textposition="bottom center",
            textfont=dict(size=9, color=C["muted"]),
            hovertext=["Host %s<br>%s port %s" % (
                h["mac"], names.get(h["dpid"], h["dpid"]), h["port"])
                for h in pts], hoverinfo="text",
            marker=dict(size=11, symbol="diamond", color=C["slate"],
                        line=dict(color=C["text"], width=1))))

    # 6) Switchler
    health_color = {"HEALTHY": C["cyan"], "DEGRADED": C["amber"],
                    "FAILED": C["red"]}
    xs, ys, colors, texts, hovers = [], [], [], [], []
    inv_by_dpid = dict((i["dpid"], i) for i in inventory if i.get("dpid"))
    for dpid in sorted(nodes, key=lambda d: sr._natural_key(names.get(d, d))):
        if dpid not in pos:
            continue
        xs.append(pos[dpid][0])
        ys.append(pos[dpid][1])
        inv = inv_by_dpid.get(dpid, {})
        sw = switches.get(dpid)
        label = names.get(dpid, sr.short_dpid(dpid))
        texts.append("<b>%s</b>" % esc(label))
        if sw is None:
            colors.append(C["slate"])
            hovers.append("<b>%s</b><br>DPID %s<br>Controller'a BAĞLI DEĞİL"
                          % (esc(label), dpid))
            continue
        colors.append(health_color.get(sw.get("health"), C["cyan"]))
        bad = [p for p in as_list(sw.get("ports"))
               if p.get("health") not in (None, "HEALTHY")]
        hovers.append(
            "<b>%s</b><br>DPID %s<br>Mgmt IP: %s<br>Sağlık: %s<br>"
            "Port: %s · ISL port: %s<br>Öğrenilen MAC: %s%s" % (
                esc(label), dpid, esc(inv.get("mgmt_ip") or sw.get("address")
                                      or "-"),
                sw.get("health"), sw.get("port_count"),
                ", ".join(str(p) for p in as_list(sw.get("isl_ports")))
                or "-", sw.get("learned_macs"),
                "".join("<br>⚠ p%s %s (%s)" % (p["port_no"], p["health"],
                                              p.get("health_reason") or "-")
                        for p in bad[:6])))
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", name="Switch", text=texts,
        textposition="bottom center",
        textfont=dict(size=16 if presentation else 13, color=C["text"]),
        hovertext=hovers, hoverinfo="text",
        marker=dict(size=46 if presentation else 40, color=colors,
                    symbol="circle",
                    line=dict(color="#0b1120", width=3),
                    opacity=0.95)))

    fig.update_layout(
        template="plotly_dark", height=430 if presentation else 540,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False, range=_axis_range(pos, 0)),
        yaxis=dict(visible=False, range=_axis_range(pos, 1),
                   scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", yanchor="bottom", y=0.0, x=0.0,
                    bgcolor="rgba(11,17,32,.6)", font=dict(size=11)),
        hoverlabel=dict(bgcolor=C["card"], bordercolor=C["border"],
                        font=dict(color=C["text"], size=12)),
        dragmode=False)
    return fig


def _axis_range(pos, i):
    if not pos:
        return [-1, 1]
    vals = [p[i] for p in pos.values()]
    lo, hi = min(vals), max(vals)
    pad = max(0.35, (hi - lo) * 0.18)
    return [lo - pad, hi + pad]


# ----------------------------------------------------------------------
# Agent kartları
# ----------------------------------------------------------------------
def agent_card(title, subtitle, status, stats, last):
    stat_html = "".join('<div class="stat"><div class="n">%s</div>'
                        '<div class="t">%s</div></div>' % (esc(v), esc(k))
                        for k, v in stats)
    last = as_dict(last)
    if last:
        last_html = ('<div class="last"><span class="ev" style="color:%s">'
                     '%s</span> · <span class="muted">%s · %s</span>'
                     '<div class="msg">%s</div></div>'
                     % (SOURCE_COLOR.get(last.get("source"), C["muted"]),
                        esc(last.get("event")), esc(clock_time(last.get("t"))),
                        esc(sr.ago(last.get("t"))),
                        esc((last.get("message") or "")[:170])))
    else:
        last_html = '<div class="last"><span class="muted">Henüz olay yok' \
                    '</span></div>'
    return ('<div class="card"><div class="agent-head"><div class="agent-name">'
            '%s<small>%s</small></div>%s</div><div class="stats">%s</div>%s'
            '</div>' % (esc(title), esc(subtitle), pill(status), stat_html,
                        last_html))


def render_agents(state, names):
    agents = as_dict(state.get("agents"))
    mon = as_dict(agents.get("monitoring"))
    fail = as_dict(agents.get("failure"))
    rout = as_dict(agents.get("routing"))
    rec = as_dict(agents.get("recovery"))
    last_dec = as_dict(rout.get("last_decision"))
    cards = [
        agent_card("Monitoring Agent", "OpenFlow port istatistikleri · LLDP",
                   mon.get("status", "?"),
                   [("izlenen port", mon.get("ports_tracked", 0)),
                    ("metrik örneği", mon.get("metric_count", 0)),
                    ("son metrik", sr.ago(mon.get("last_metrics_at")))],
                   mon.get("last_event")),
        agent_card("Failure Detection Agent", "Kural tabanlı port sağlığı",
                   fail.get("status", "?"),
                   [("HEALTHY", fail.get("healthy", 0)),
                    ("DEGRADED", fail.get("degraded", 0)),
                    ("FAILED", fail.get("failed", 0))],
                   fail.get("last_event")),
        agent_card("Routing Agent", "Canlı graph üzerinde alternatif yol",
                   rout.get("status", "?"),
                   [("karar", rout.get("decisions", 0)),
                    ("yol yok", rout.get("no_path", 0)),
                    ("son hop", last_dec.get("hop_count", "-"))],
                   rout.get("last_event")),
        agent_card("Recovery Agent", "OpenFlow self-healing + failback",
                   rec.get("status", "?"),
                   [("aktif oturum", rec.get("active_sessions", 0)),
                    ("failback bekl.", rec.get("failback_pending", 0)),
                    ("bilinen host", rec.get("known_hosts", 0))],
                   rec.get("last_event")),
    ]
    st.markdown('<div class="grid agent-grid">%s</div>' % "".join(cards),
                unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Self-healing / recovery
# ----------------------------------------------------------------------
def render_incident(state, names):
    inc = as_dict(state.get("latest_failure"))
    if not inc:
        st.markdown('<div class="card"><div class="empty">Henüz failure '
                    'olayı yok. Bir link düştüğünde veya port DEGRADED '
                    'olduğunda algılama → routing → recovery zinciri burada '
                    'adım adım görünür.</div></div>', unsafe_allow_html=True)
        return
    status = inc.get("status")
    link = (sr.pretty_link(inc.get("link"), names) if inc.get("link")
            else "host portu %s" % (inc.get("port") or "-"))
    reason = inc.get("outcome_reason")
    reason_html = ""
    if reason:
        reason_html = ('<div class="k">Sonuç nedeni</div><div>%s<br>'
                       '<span class="muted">%s</span></div>'
                       % (esc(reason), esc(REASON_TEXT.get(reason, ""))))
    rec_ms = inc.get("recovery_ms")
    big = ""
    if rec_ms is not None:
        big = ('<div style="text-align:right"><div class="big-num">%.1f ms'
               '</div><div class="muted">algılama → recovery yolu aktif<br>'
               '(controller içi tepki süresi)</div></div>' % rec_ms)
    rows = []
    for s in as_list(inc.get("steps")):
        step = s.get("step", "")
        t = ("ok" if step in ("PATH_ACTIVE", "FAILBACK_COMPLETE", "LINK_UP",
                              "PORT_RECOVERED") else
             "violet" if step == "ROUTE_SELECTED" else
             "err" if step in ("DETECTED", "NO_ALTERNATIVE_PATH",
                               "FLOW_INSTALL_FAILED") else
             "warn" if step.startswith("FAILBACK") or step == "CONFIRMED"
             else "info")
        rows.append('<div class="tl-row tone-%s"><div class="tl-step">%s</div>'
                    '<div class="tl-dt">+%s ms</div><div class="tl-detail">%s'
                    '</div></div>' % (t, esc(step), esc(fmt_num(
                        s.get("dt_ms"), "%.1f")), esc(s.get("detail"))))
    st.markdown("""
<div class="card">
 <div style="display:flex;justify-content:space-between;gap:12px;
             flex-wrap:wrap">
  <div>
   <div class="muted">SON FAILURE · #%s · %s (%s)</div>
   <div style="font-size:1.15rem;font-weight:750;margin:4px 0 8px 0">%s</div>
   <div class="kv">
     <div class="k">Tür</div><div>%s %s</div>
     <div class="k">Etkilenen link</div><div>%s</div>
     <div class="k">Failure reason</div><div>%s</div>
     %s
   </div>
  </div>%s
 </div>
 <div class="timeline">%s</div>
</div>""" % (inc.get("id"), esc(clock_time(inc.get("started"))),
             esc(sr.ago(inc.get("started"))), esc(link),
             pill(inc.get("kind"), inc.get("kind")), pill(status),
             esc(link), esc(inc.get("reason")), reason_html, big,
             "".join(rows)), unsafe_allow_html=True)


def render_route_and_sessions(state, names):
    route = as_dict(state.get("latest_route"))
    recovery = as_dict(state.get("recovery"))
    sessions = as_list(recovery.get("sessions"))
    if route:
        hops = '<span class="arrow">→</span>'.join(
            '<span class="hop">%s</span>' % esc(names.get(d, sr.short_dpid(d)))
            for d in as_list(route.get("path")))
        st.markdown("""
<div class="card">
 <div class="muted">ROUTING AGENT · SEÇİLEN ALTERNATİF PATH · %s</div>
 <div class="path">%s</div>
 <div class="kv">
  <div class="k">Hop count</div><div><b>%s</b></div>
  <div class="k">Tetikleyici</div><div>%s · %s</div>
  <div class="k">Etkilenen link</div><div>%s</div>
  <div class="k">Hariç tutulan edge</div><div>%s</div>
 </div>
</div>""" % (esc(sr.ago(route.get("t"))), hops, esc(route.get("hop_count")),
             esc(route.get("trigger")), esc(route.get("reason")),
             esc(sr.pretty_link(route.get("affected_link"), names)),
             esc(route.get("excluded_edges"))), unsafe_allow_html=True)
    else:
        st.markdown('<div class="card"><div class="muted">ROUTING AGENT'
                    '</div><div class="empty">Henüz alternatif yol kararı '
                    'yok.</div></div>', unsafe_allow_html=True)

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
    if sessions:
        rows = []
        for s in sessions:
            fb = ("PENDING (%s sn)" % fmt_num(s.get("failback_in_sec"), "%.0f")
                  if s.get("state") == "FAILBACK_PENDING" else "bekliyor: link")
            for p in as_list(s.get("pairs")) or [{}]:
                rows.append({
                    "Link": sr.pretty_link(s.get("link"), names),
                    "Durum": s.get("state"), "Tetik": s.get("trigger"),
                    "Host çifti": p.get("pair", "-"),
                    "Recovery path": sr.pretty_path(p.get("path"), names),
                    "Flow": p.get("flows", 0), "Failback": fb,
                    "Başlangıç": sr.ago(s.get("started"))})
        st.markdown('<div class="muted" style="margin-bottom:6px">RECOVERY '
                    'AGENT · AKTİF OTURUMLAR (recovery flow durumu)</div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.markdown('<div class="card"><div class="muted">RECOVERY AGENT'
                    '</div><div class="empty">Aktif recovery oturumu yok — '
                    'trafik normal learning forwarding ile akıyor. Failback '
                    'tamamlandığında oturum burada kapanır.</div></div>',
                    unsafe_allow_html=True)


def render_incident_history(state, names):
    incidents = list(reversed(as_list(state.get("incidents"))))
    if not incidents:
        return
    rows = [{"#": i.get("id"), "Zaman": clock_time(i.get("started")),
             "Tür": i.get("kind"), "Durum": i.get("status"),
             "Link / port": (sr.pretty_link(i.get("link"), names)
                             if i.get("link") else i.get("port")),
             "Alternatif path": sr.pretty_path(
                 as_dict(i.get("route")).get("path"), names) or "-",
             "Hop": as_dict(i.get("route")).get("hop_count"),
             "Recovery (ms)": i.get("recovery_ms"),
             "Neden": i.get("outcome_reason") or i.get("reason")}
            for i in incidents]
    with st.expander("Incident geçmişi (%d)" % len(rows)):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ----------------------------------------------------------------------
# Monitoring
# ----------------------------------------------------------------------
def port_rows(state, names):
    metrics = dict(("%s:%s" % (m.get("dpid"), m.get("port_no")), m)
                   for m in as_list(as_dict(state.get("metrics")).get("ports")))
    rows = []
    for sw in as_list(state.get("switches")):
        for p in as_list(sw.get("ports")):
            key = "%s:%s" % (sw["dpid"], p["port_no"])
            m = metrics.get(key, {})
            link_up = p.get("link_up")
            admin = p.get("admin_up")
            status = ("?" if link_up is None else
                      "UP" if link_up and admin is not False else "DOWN")
            rows.append({
                "_key": key, "_dpid": sw["dpid"],
                "Switch": names.get(sw["dpid"], sr.short_dpid(sw["dpid"])),
                "Port": p["port_no"], "Ad": p.get("name") or "-",
                "Durum": status, "Sağlık": p.get("health") or "-",
                "ISL": "evet" if p.get("is_isl") else "",
                "Throughput (Mbps)": m.get("throughput_mbps"),
                "RX Mbps": m.get("rx_mbps"), "TX Mbps": m.get("tx_mbps"),
                "Paket/sn": m.get("packet_rate"),
                "Drop Δ": m.get("drop_delta"),
                "Drop %": (m["drop_ratio"] * 100
                           if isinstance(m.get("drop_ratio"), (int, float))
                           else None),
                "Error Δ": m.get("error_delta"),
                "RX drop": m.get("rx_dropped"), "TX drop": m.get("tx_dropped"),
                "RX err": m.get("rx_errors"), "TX err": m.get("tx_errors"),
                "Güncelleme": sr.ago(m.get("updated")) if m else "baseline"})
    return rows


def render_monitoring(state, names):
    rows = port_rows(state, names)
    if not rows:
        st.markdown('<div class="card"><div class="empty">Henüz port '
                    'verisi yok (controller ilk PortDesc/PortStats '
                    'cevaplarını bekliyor).</div></div>',
                    unsafe_allow_html=True)
        return
    switch_opts = ["Tümü"] + sorted(set(r["Switch"] for r in rows),
                                    key=sr._natural_key)
    c1, c2, c3, c4 = st.columns([1.2, 2.2, 1, 1])
    sel_sw = c1.selectbox("Switch", switch_opts, key="mon_switch")
    in_sw = [r for r in rows if sel_sw == "Tümü" or r["Switch"] == sel_sw]
    port_labels = dict((r["_key"], "%s · p%s (%s)" % (r["Switch"], r["Port"],
                                                     r["Ad"])) for r in in_sw)
    sel_ports = c2.multiselect(
        "Port", list(port_labels), format_func=port_labels.get,
        key="mon_ports_%s" % sel_sw, placeholder="Tüm portlar")
    only_isl = c3.toggle("Yalnızca ISL", key="mon_isl")
    only_traffic = c4.toggle("Trafik olanlar", key="mon_traffic")

    view = [r for r in in_sw
            if (not sel_ports or r["_key"] in sel_ports)
            and (not only_isl or r["ISL"])
            and (not only_traffic or (r["Paket/sn"] or 0) > 0)]
    df = pd.DataFrame(view)
    if df.empty:
        st.markdown('<div class="empty">Filtreye uyan port yok.</div>',
                    unsafe_allow_html=True)
    else:
        max_thr = max([r["Throughput (Mbps)"] or 0 for r in view] + [0.001])
        st.dataframe(
            df.drop(columns=["_key", "_dpid"]), hide_index=True,
            width="stretch", height=min(420, 38 + 35 * len(view)),
            column_config={
                "Throughput (Mbps)": st.column_config.ProgressColumn(
                    "Throughput (Mbps)", min_value=0.0, max_value=max_thr,
                    format="%.3f"),
                "RX Mbps": st.column_config.NumberColumn(format="%.3f"),
                "TX Mbps": st.column_config.NumberColumn(format="%.3f"),
                "Paket/sn": st.column_config.NumberColumn(format="%.1f"),
                "Drop %": st.column_config.NumberColumn(format="%.2f%%"),
            })
    st.caption("Kaynak: OpenFlow 1.3 PortStats (5 sn aralık). Throughput = "
               "RX+TX bit hızı; drop/error değerleri switch port "
               "sayaçlarından gelir. Uçtan uca packet loss/latency (ping) "
               "ölçümü sistemde henüz yok.")
    render_history(state, names, view, sel_ports)


def render_history(state, names, view, sel_ports):
    history = as_dict(as_dict(state.get("metrics")).get("history"))
    if not history:
        return
    metric = st.radio("Grafik", ["Throughput (Mbps)", "Paket/sn"],
                      horizontal=True, key="mon_metric",
                      label_visibility="collapsed")
    idx = 1 if metric.startswith("Throughput") else 2
    fig = go.Figure()
    if sel_ports and len(sel_ports) <= 8:
        label = dict((r["_key"], "%s · p%s" % (r["Switch"], r["Port"]))
                     for r in view)
        for key in sel_ports:
            pts = as_list(history.get(key))
            if pts:
                fig.add_trace(go.Scatter(
                    x=[datetime.fromtimestamp(p[0]) for p in pts],
                    y=[p[idx] for p in pts], mode="lines",
                    name=label.get(key, key), line=dict(width=2)))
        title = "Seçili portlar"
    else:
        # Switch başına toplam (aynı PortStats cevabı ≈ aynı saniye)
        dpids = sorted(set(r["_dpid"] for r in view))
        for dpid in dpids:
            agg = {}
            for key, pts in history.items():
                if key.rsplit(":", 1)[0] != dpid:
                    continue
                for p in pts:
                    if isinstance(p[idx], (int, float)):
                        sec = int(round(p[0]))
                        agg[sec] = agg.get(sec, 0.0) + p[idx]
            if agg:
                xs = sorted(agg)
                fig.add_trace(go.Scatter(
                    x=[datetime.fromtimestamp(x) for x in xs],
                    y=[agg[x] for x in xs], mode="lines",
                    name=names.get(dpid, sr.short_dpid(dpid)),
                    line=dict(width=2, shape="spline", smoothing=0.6)))
        title = "Switch başına toplam"
    fig.update_layout(
        template="plotly_dark", height=280, title=dict(
            text="%s · %s (son ~5 dk)" % (metric, title),
            font=dict(size=13, color=C["muted"])),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.2),
        xaxis=dict(gridcolor="#1f2b46"), yaxis=dict(gridcolor="#1f2b46"))
    st.plotly_chart(fig, width="stretch", key="mon_chart",
                    config={"displayModeBar": False})


# ----------------------------------------------------------------------
# OVS tablosu
# ----------------------------------------------------------------------
def render_ovs_table(state, names, inventory, inv_error, status):
    switches = dict((s["dpid"], s) for s in as_list(state.get("switches")))
    inv = dict((i["dpid"], i) for i in inventory if i.get("dpid"))
    rows = []
    for dpid in sorted(set(switches) | set(inv),
                       key=lambda d: sr._natural_key(names.get(d, d))):
        sw, it = switches.get(dpid), inv.get(dpid, {})
        connected = sw is not None and status == "ONLINE"
        if sw is None:
            st_txt = "BAĞLI DEĞİL"
        elif sw.get("health") == "HEALTHY":
            st_txt = "AKTİF"
        else:
            st_txt = "UYARI (%s)" % sw.get("health")
        rows.append({
            "Switch": names.get(dpid, sr.short_dpid(dpid)),
            "DPID": dpid,
            "Mgmt IF": it.get("mgmt_if") or "-",
            "Mgmt IP": it.get("mgmt_ip") or (sw or {}).get("address") or "-",
            "OpenFlow (controller)": "✅ BAĞLI" if connected else "❌ YOK",
            "OVS is_connected": {True: "✅ true", False: "❌ false"}.get(
                it.get("ovs_connected"), "-"),
            "Port": (sw or {}).get("port_count"),
            "ISL port": ", ".join(str(p) for p in
                                  as_list((sw or {}).get("isl_ports"))) or "-",
            "Öğrenilen MAC": (sw or {}).get("learned_macs"),
            "Durum": st_txt})
    # DPID'si okunamayan container'lar (ör. ovs-vswitchd henüz hazır değil)
    for it in inventory:
        if not it.get("dpid"):
            rows.append({"Switch": it.get("name"), "DPID": "-",
                         "Mgmt IF": it.get("mgmt_if") or "-",
                         "Mgmt IP": it.get("mgmt_ip") or "-",
                         "OpenFlow (controller)": "❌ YOK",
                         "OVS is_connected": "-", "Port": None,
                         "ISL port": "-", "Öğrenilen MAC": None,
                         "Durum": "OKUNAMADI: %s" % (it.get("error") or "?")})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.markdown('<div class="empty">Switch yok.</div>',
                    unsafe_allow_html=True)
    if inv_error:
        st.caption("Docker envanteri alınamadı (%s); adlar DPID'den "
                   "türetildi, Mgmt IP controller bağlantı adresidir."
                   % inv_error)
    elif not st.session_state.get("opt_docker", True):
        st.caption("Docker envanteri kapalı; adlar DPID'den türetildi.")


# ----------------------------------------------------------------------
# Olay günlüğü
# ----------------------------------------------------------------------
def render_event_log(state):
    events = list(reversed(as_list(state.get("events"))))
    sources = ["MONITORING", "FAILURE", "ROUTING", "RECOVERY", "CONTROLLER"]
    c1, c2, c3 = st.columns([2.4, 1, 1.6])
    sel = c1.multiselect("Kaynak", sources, default=sources, key="log_src")
    level = c2.selectbox("Seviye", ["Tümü", "WARNING+"], key="log_level")
    query = c3.text_input("Ara", key="log_q", placeholder="ör. FAILBACK, "
                          "0000a6e4…")
    q = query.strip().lower()
    shown = [e for e in events if e.get("source") in sel
             and (level == "Tümü" or e.get("level") in ("WARNING", "ERROR",
                                                       "CRITICAL"))
             and (not q or q in (e.get("message") or "").lower()
                  or q in (e.get("event") or "").lower())][:200]
    if not shown:
        st.markdown('<div class="log"><div class="empty" style="padding:'
                    '16px">Gösterilecek olay yok.</div></div>',
                    unsafe_allow_html=True)
        return
    rows = []
    for e in shown:
        src = e.get("source", "")
        msg = e.get("message") or ""
        ev = e.get("event") or ""
        body = esc(msg[len(ev):]) if msg.startswith(ev) else esc(msg)
        rows.append(
            '<div class="log-row %s"><div class="log-time">%s</div>'
            '<div class="log-src" style="color:%s">%s</div>'
            '<div class="log-msg"><b>%s</b>%s</div></div>'
            % (esc(e.get("level")), esc(clock_time(e.get("t"), ms=True)),
               SOURCE_COLOR.get(src, C["muted"]), esc(src), esc(ev), body))
    st.markdown('<div class="log">%s</div>' % "".join(rows),
                unsafe_allow_html=True)
    st.caption("Son %d olay (en yeni üstte). Port başına 5 sn'lik METRIC "
               "satırları burada gösterilmez; metrikler yukarıdaki tabloda."
               % len(shown))


# ----------------------------------------------------------------------
# Sayfa
# ----------------------------------------------------------------------
@st.fragment(run_every=REFRESH_SEC)
def live_view():
    state, err, age, paused = read_live_state()
    procs = sr.controller_processes()
    status, detail = sr.controller_status(state, age)
    if st.session_state.get("opt_docker", True):
        inventory, inv_error = cached_inventory()
    else:
        inventory, inv_error = [], None

    render_header(status, detail, age, paused)

    if len(procs) > 1:
        st.markdown(
            '<div class="banner warn">⚠ <b>%d controller süreci</b> çalışıyor '
            '(PID: %s). Switch\'ler farklı süreçlere bölünebilir ve state '
            'dosyası süreçler arasında gidip gelebilir. Fazla olanı elle '
            'kapatın (dashboard hiçbir süreci kapatmaz).</div>'
            % (len(procs), ", ".join(str(p["pid"]) for p in procs)),
            unsafe_allow_html=True)
    if state is None:
        st.markdown(
            '<div class="banner err">Controller verisi yok: %s<br>Controller'
            "'ı başlatın: <code>./start_sdn.sh</code> veya <code>osken-"
            "manager --observe-links controller/sdn_controller.py</code>"
            '</div>' % esc(err), unsafe_allow_html=True)
        return
    if status != "ONLINE":
        st.markdown('<div class="banner %s">Controller %s — %s. Aşağıda '
                    '<b>son bilinen durum</b> gösteriliyor.</div>'
                    % ("err" if status == "OFFLINE" else "warn", status,
                       esc(detail)), unsafe_allow_html=True)
    if err:
        st.markdown('<div class="banner warn">%s (son geçerli durum '
                    'kullanılıyor)</div>' % esc(err), unsafe_allow_html=True)

    names = sr.name_map(state, inventory)
    if st.session_state.get("view_mode") == pres.MODE_NAME:
        pres.render(state, status, names, inventory, topology_figure)
        return
    render_kpis(state, status, inventory)

    left, right = st.columns([1.45, 1], gap="medium")
    with left:
        section("Canlı topoloji")
        fig = topology_figure(state, names, inventory,
                              st.session_state.get("opt_hosts", False))
        st.plotly_chart(fig, width="stretch", key="topology",
                        config={"displayModeBar": False})
        topo = as_dict(state.get("topology"))
        st.caption("Kaynak: controller'ın canlı NetworkX graph'ı (LLDP link "
                   "discovery). %s node · %s edge. Kesikli kırmızı = FAILED, "
                   "noktalı sarı = DEGRADED, yeşil hale = aktif recovery "
                   "yolu." % (topo.get("node_count", "-"),
                              topo.get("edge_count", "-")))
    with right:
        section("Agent durumları")
        render_agents(state, names)

    section("Self-healing / Recovery")
    c1, c2 = st.columns([1.35, 1], gap="medium")
    with c1:
        render_incident(state, names)
    with c2:
        render_route_and_sessions(state, names)
    render_incident_history(state, names)

    section("Monitoring · port metrikleri")
    render_monitoring(state, names)

    section("Open vSwitch'ler")
    render_ovs_table(state, names, inventory, inv_error, status)

    section("Canlı olay günlüğü")
    render_event_log(state)


def main():
    st.set_page_config(page_title="Smart SDN Dashboard", page_icon="🛰️",
                       layout="wide", initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(pres.CSS, unsafe_allow_html=True)
    modes = [pres.DETAIL_NAME, pres.MODE_NAME]
    if "view_mode" not in st.session_state:
        wanted = str(st.query_params.get("mode", "")).lower()
        st.session_state["view_mode"] = (pres.MODE_NAME if wanted == "sunum"
                                         else pres.DETAIL_NAME)
    st.radio("Görünüm", modes, key="view_mode", horizontal=True,
             label_visibility="collapsed")
    with st.sidebar:
        st.markdown("### Ayarlar")
        st.toggle("Canlı yenileme (%d sn)" % REFRESH_SEC, value=True,
                  key="opt_live")
        st.toggle("OVS adlarını Docker'dan al", value=True, key="opt_docker",
                  help="Salt okunur: docker ps + ovs-vsctl get + ip addr")
        st.toggle("Topolojide hostları göster", value=False, key="opt_hosts")
        st.divider()
        st.caption("State dosyası: `%s`" % sr.STATE_PATH)
        st.caption("Dashboard yalnızca gözlemler; controller, agent veya "
                   "OVS ayarlarına yazmaz.")
    live_view()


main()
