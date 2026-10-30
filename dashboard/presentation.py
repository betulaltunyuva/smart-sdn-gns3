"""
Smart SDN (GNS3) - Aşama 7.7: Sunum Modu (salt okunur)

Tek ekranda: KPI'lar, canlı topoloji, Monitoring → Failure Detection →
Routing → Recovery hattı ve self-healing zaman çizelgesi.

Yalnızca runtime/state.json içindeki gerçek veriyi yorumlar; hiçbir değer
üretilmez. Veri yoksa "Veri yok" yazılır. Sistem kural tabanlıdır, yapay
zekâ modeli yoktur.
"""

import html
import re
import time
from datetime import datetime

import streamlit as st

import state_reader as sr

MODE_NAME = "Sunum Modu"
DETAIL_NAME = "Detaylı Panel"
NO_DATA = "Veri yok"

CSS = """
<style>
.pm-kpis { display:grid; gap:12px; grid-template-columns:repeat(5,1fr); }
@media (max-width: 1000px) { .pm-kpis { grid-template-columns:repeat(2,1fr); } }
.pm-kpi { background:#111a2e; border:1px solid #1f2b46; border-radius:14px;
          padding:12px 16px; border-left:4px solid var(--c,#64748b); }
.pm-kpi .l { color:#8b9bb8; font-size:.72rem; font-weight:600;
             letter-spacing:.08em; text-transform:uppercase; }
.pm-kpi .v { font-size:2rem; font-weight:800; line-height:1.15;
             color:var(--c,#e2e8f0); }
.pm-kpi .s { color:#8b9bb8; font-size:.78rem; }
.pm-flow { display:flex; flex-direction:column; gap:4px; }
.pm-ag { background:#111a2e; border:1px solid #1f2b46; border-radius:12px;
         padding:9px 12px; border-left:4px solid var(--c,#64748b); }
.pm-ag.hot { box-shadow:0 0 0 1px var(--c) inset; background:#13203a; }
.pm-ag .h { display:flex; justify-content:space-between; align-items:center; }
.pm-ag .n { font-weight:750; font-size:.95rem; }
.pm-ag .d { color:#cbd5e1; font-size:.8rem; margin:2px 0; }
.pm-ag .m { color:#8b9bb8; font-size:.74rem; }
.pm-arrow { text-align:center; color:#64748b; font-size:.9rem; line-height:1; }
.pm-pill { padding:1px 9px; border-radius:999px; font-size:.68rem;
           font-weight:700; border:1px solid currentColor; }
.pm-steps { display:grid; gap:8px;
            grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); }
.pm-step { background:#111a2e; border:1px solid #1f2b46; border-radius:12px;
           padding:10px 12px; border-top:4px solid var(--c,#334155); }
.pm-step .no { color:var(--c); font-weight:800; font-size:.75rem; }
.pm-step .t { font-weight:700; font-size:.88rem; margin:2px 0; }
.pm-step .a { color:#8b9bb8; font-size:.72rem; }
.pm-step .x { color:var(--c); font-family:ui-monospace,monospace;
              font-size:.85rem; font-weight:700; margin-top:4px; }
.pm-step .dd { color:#cbd5e1; font-size:.74rem; margin-top:3px; }
.pm-note { background:rgba(96,165,250,.08); border:1px solid
           rgba(96,165,250,.35); border-radius:10px; padding:8px 12px;
           font-size:.82rem; margin-top:8px; color:#cbd5e1; }
.pm-note.warn { background:rgba(251,191,36,.08);
                border-color:rgba(251,191,36,.4); }
.pm-badge { display:inline-block; padding:2px 10px; border-radius:999px;
            font-size:.72rem; font-weight:700; margin-left:8px; }
.pm-card { background:#111a2e; border:1px solid #1f2b46; border-radius:14px;
           padding:12px 16px; }
.pm-card .t { color:#8b9bb8; font-size:.72rem; font-weight:600;
              letter-spacing:.08em; text-transform:uppercase; }
</style>
"""

COL = {"ok": "#34d399", "info": "#60a5fa", "warn": "#fbbf24",
       "err": "#f87171", "muted": "#64748b", "violet": "#a78bfa",
       "cyan": "#22d3ee"}

SKIP_TEXT = {
    "no_affected_host_traffic":
        "Atlandı (hata değil): Düşen linki kullanan bilinen host trafiği "
        "yoktu, bu yüzden özel kurtarma kuralı yüklemeye gerek kalmadı.",
    "insufficient_forwarding_context":
        "Atlandı: Host konumları yeterince öğrenilmediği için güvenli bir "
        "kurtarma kuralı üretilemedi; trafik normal öğrenme (learning "
        "switch) ile yeniden öğrenilir.",
    "execution_disabled":
        "Atlandı: Recovery yürütmesi bu çalışmada devre dışı.",
    "invalid_request":
        "Atlandı: Routing isteği doğrulamadan geçmedi.",
}
NO_PATH_TEXT = {
    "disconnected": "Kalan topolojide iki uç arasında alternatif yol yok.",
}


def esc(v):
    return html.escape("" if v is None else str(v))


def as_list(v):
    return v if isinstance(v, list) else []


def as_dict(v):
    return v if isinstance(v, dict) else {}


def fmt_ms(ms):
    if not isinstance(ms, (int, float)):
        return NO_DATA
    if ms < 1000:
        return "%.1f ms" % ms
    if ms < 60000:
        return "%.1f sn" % (ms / 1000.0)
    return sr.fmt_duration(ms / 1000.0)


def clock(ts):
    if not isinstance(ts, (int, float)):
        return "-"
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def section(title):
    st.markdown('<div class="section">%s</div>' % esc(title),
                unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Incident yorumlama
# ----------------------------------------------------------------------
def active_incident(state):
    """Şu an GERÇEKTEN süren incident (yoksa None). Ölçüt: linki şu an
    kopuk / DEGRADED ya da aktif recovery oturumu var."""
    live = set(l.get("id") for l in as_list(state.get("failed_links")))
    live |= set(l.get("id") for l in as_list(state.get("links"))
                if l.get("status") == "DEGRADED")
    live |= set(s.get("link") for s in as_list(
        as_dict(state.get("recovery")).get("sessions")))
    live.discard(None)
    for inc in reversed(as_list(state.get("incidents"))):
        if inc.get("link") in live:
            return inc
    return None


def last_recovered(state):
    """PATH_ACTIVE'e ulaşmış (recovery_ms ölçülmüş) son incident."""
    for inc in reversed(as_list(state.get("incidents"))):
        if inc.get("recovery_ms") is not None:
            return inc
    return None


def _first(steps, name):
    for s in steps:
        if s.get("step") == name:
            return s
    return None


def _events_for(state, inc, event):
    link, t0 = inc.get("link"), inc.get("started") or 0
    out = []
    for e in as_list(state.get("events")):
        if e.get("event") == event and (e.get("t") or 0) >= t0 - 0.001:
            msg = e.get("message") or ""
            if event == "FLOW_INSTALLED" or (link and link in msg):
                out.append(e)
    return out


def _reason_of(detail):
    m = re.search(r"reason=(\w+)", detail or "")
    return m.group(1) if m else None


def build_stages(state, inc, names, live):
    """Incident adımlarını 6 (+failback) aşamaya eşler. Her aşama:
    (başlık, agent, durum[done|skip|wait|fail|na], süre_ms, açıklama)."""
    steps = as_list(inc.get("steps"))
    det, conf = _first(steps, "DETECTED"), _first(steps, "CONFIRMED")
    route = _first(steps, "ROUTE_SELECTED")
    nopath = _first(steps, "NO_ALTERNATIVE_PATH")
    fstart = _first(steps, "FLOW_INSTALL_START")
    ffail = _first(steps, "FLOW_INSTALL_FAILED")
    skipped = _first(steps, "RECOVERY_SKIPPED")
    active = _first(steps, "PATH_ACTIVE")
    up = _first(steps, "LINK_UP") or _first(steps, "PORT_RECOVERED")
    wait = "wait" if live else "na"
    st_ = []

    link = (sr.pretty_link(inc.get("link"), names) if inc.get("link")
            else "port %s" % (inc.get("port") or "-"))
    st_.append(("Arıza algılandı", "Monitoring",
                "done" if det else wait, det and det.get("dt_ms"), link))
    st_.append(("Arıza doğrulandı", "Failure Detection",
                "done" if conf else wait, conf and conf.get("dt_ms"),
                "Kural tabanlı port/link sağlık kararı"))
    if route:
        hops = as_dict(inc.get("route")).get("hop_count")
        path = sr.pretty_path(as_dict(inc.get("route")).get("path"), names)
        st_.append(("Alternatif yol hesaplandı", "Routing", "done",
                    route.get("dt_ms"), "%s hop · %s" % (hops, path)))
    elif nopath:
        r = inc.get("outcome_reason")
        st_.append(("Alternatif yol aranıyor", "Routing", "fail",
                    nopath.get("dt_ms"),
                    NO_PATH_TEXT.get(r, "Alternatif yol bulunamadı (%s)." % r)))
    else:
        st_.append(("Alternatif yol hesaplandı", "Routing", wait, None, ""))

    if fstart:
        flows = re.search(r"flows=(\d+)", fstart.get("detail") or "")
        n_inst = len(_events_for(state, inc, "FLOW_INSTALLED")) \
            if live else 0
        extra = (" · %d FLOW_INSTALLED olayı" % n_inst) if n_inst else ""
        st_.append(("OpenFlow kuralları yüklendi", "Recovery", "done",
                    fstart.get("dt_ms"),
                    "%s flow planlandı%s" % (flows.group(1) if flows else "?",
                                             extra)))
    elif skipped:
        st_.append(("OpenFlow kuralları", "Recovery", "skip",
                    skipped.get("dt_ms"),
                    SKIP_TEXT.get(_reason_of(skipped.get("detail")),
                                  "Atlandı: " + str(_reason_of(
                                      skipped.get("detail"))))))
    elif ffail:
        st_.append(("OpenFlow kuralları", "Recovery", "fail",
                    ffail.get("dt_ms"), "Flow yükleme başarısız"))
    elif nopath:
        st_.append(("OpenFlow kuralları", "Recovery", "na", None,
                    "Yol olmadığı için kural üretilmedi"))
    else:
        st_.append(("OpenFlow kuralları yüklendi", "Recovery", wait, None, ""))

    if active:
        st_.append(("Alternatif yol etkin", "Recovery", "done",
                    active.get("dt_ms"),
                    "PATH_ACTIVE · algılama → yol aktif (controller içi)"))
    elif skipped or nopath:
        st_.append(("Alternatif yol etkin", "Recovery", "na", None,
                    "Gerekmedi" if skipped else "Yol olmadığı için yok"))
    else:
        st_.append(("Alternatif yol etkin", "Recovery", wait, None, ""))

    if up:
        st_.append(("Bağlantı yeniden kuruldu", "Controller", "done",
                    up.get("dt_ms"), "Arıza başlangıcından itibaren"))
    else:
        st_.append(("Bağlantı yeniden kuruldu", "Controller",
                    "wait" if live else "na", None,
                    "Link bekleniyor" if live else "Veri yok"))

    fb = [_first(steps, n) for n in ("FAILBACK_PENDING", "FAILBACK_START",
                                     "FAILBACK_COMPLETE")]
    if any(fb):
        done = fb[2]
        st_.append(("Normal yönlendirmeye dönüş", "Recovery (failback)",
                    "done" if done else "wait",
                    (done or fb[1] or fb[0]).get("dt_ms"),
                    "Recovery flow'ları kaldırıldı, learning forwarding "
                    "geri geldi" if done else "Link stabil olana kadar bekleniyor"))
    return st_


def invalidation_note(state, inc):
    steps = as_list(inc.get("steps"))
    inv = _first(steps, "SESSION_INVALIDATED")
    if not inv:
        return None
    removed = ""
    for e in _events_for(state, inc, "RECOVERY_FLOWS_REMOVED"):
        m = re.search(r"removed=(\d+/\d+)", e.get("message") or "")
        if m:
            removed = " Kaldırılan flow: %s." % m.group(1)
    return ("Kurtarma oturumu kapatıldı (SESSION_INVALIDATED): kurtarma "
            "yolu üzerindeki bir link de koptu veya oturum yeni arızayla "
            "değiştirildi; bu bir hata değil, oturumun sonlanmasıdır.%s" %
            removed)


# ----------------------------------------------------------------------
# Bileşenler
# ----------------------------------------------------------------------
def _kpi(label, value, sub, color):
    return ('<div class="pm-kpi" style="--c:%s"><div class="l">%s</div>'
            '<div class="v">%s</div><div class="s">%s</div></div>'
            % (color, esc(label), esc(value), esc(sub)))


def render_kpis(state, status):
    switches = as_list(state.get("switches"))
    links = as_list(state.get("links"))
    failed = as_list(state.get("failed_links"))
    degraded = [l for l in links if l.get("status") == "DEGRADED"]
    recovery = as_dict(state.get("recovery"))
    sessions = as_list(recovery.get("sessions"))
    ctl = as_dict(state.get("controller"))
    rstat = recovery.get("status") or NO_DATA
    n_fail = len(failed) + len(degraded)
    rcol = {"ACTIVE": COL["ok"], "FAILBACK_PENDING": COL["warn"]}.get(
        rstat, COL["muted"])
    rsub = ("%d oturum · %d flow" % (len(sessions), sum(
        s.get("flow_count") or 0 for s in sessions)) if sessions
        else "Aktif kurtarma oturumu yok")
    cards = [
        _kpi("Controller", status,
             "uptime %s" % (sr.fmt_duration(ctl.get("uptime_sec"))
                            if status == "ONLINE" else "-"),
             COL["ok"] if status == "ONLINE" else COL["err"]),
        _kpi("Aktif switch", len(switches), "OpenFlow bağlantılı",
             COL["info"] if switches else COL["warn"]),
        _kpi("Aktif bağlantı", len(links),
             "%d DEGRADED" % len(degraded) if degraded else "ISL linkleri",
             COL["info"] if links else COL["warn"]),
        _kpi("Aktif arıza", n_fail,
             "%d kopuk · %d degraded" % (len(failed), len(degraded)),
             COL["err"] if failed else (COL["warn"] if degraded
                                        else COL["ok"])),
        _kpi("Recovery", rstat, rsub, rcol),
    ]
    st.markdown('<div class="pm-kpis">%s</div>' % "".join(cards),
                unsafe_allow_html=True)


AGENT_ROLES = (
    ("monitoring", "Monitoring Agent", "Ağı izliyor.", COL["cyan"]),
    ("failure", "Failure Detection Agent", "Arızaları tespit ediyor.",
     COL["err"]),
    ("routing", "Routing Agent", "Alternatif yol hesaplıyor.", COL["violet"]),
    ("recovery", "Recovery Agent", "Yeni OpenFlow kurallarını uyguluyor.",
     COL["ok"]),
)
HOT_SEC = 15


def _agent_line(key, a):
    if key == "monitoring":
        return "%s port izleniyor" % a.get("ports_tracked", NO_DATA)
    if key == "failure":
        return "%s sağlıklı · %s degraded · %s failed" % (
            a.get("healthy", "-"), a.get("degraded", "-"),
            a.get("failed", "-"))
    if key == "routing":
        return "%s karar · %s kez yol bulunamadı" % (
            a.get("decisions", "-"), a.get("no_path", "-"))
    return "%s aktif oturum · %s yol etkinleştirildi" % (
        a.get("active_sessions", "-"), a.get("paths_activated", "-"))


def render_agents(state):
    agents = as_dict(state.get("agents"))
    now = time.time()
    parts = []
    for i, (key, title, role, color) in enumerate(AGENT_ROLES):
        a = as_dict(agents.get(key))
        status = a.get("status") or NO_DATA
        last = as_dict(a.get("last_event"))
        age = (now - last["t"]) if isinstance(last.get("t"),
                                              (int, float)) else None
        hot = age is not None and age <= HOT_SEC
        last_txt = ("son olay: %s · %s" % (last.get("event"),
                                           sr.ago(last.get("t")))
                    if last else "son olay: %s" % NO_DATA)
        scol = COL["ok"] if status in ("RUNNING", "ENABLED") else (
            COL["muted"] if status == "IDLE" else
            COL["info"] if status in ("ACTIVE", "FAILBACK_PENDING")
            else COL["err"])
        parts.append(
            '<div class="pm-ag%s" style="--c:%s"><div class="h"><span '
            'class="n">%d. %s</span><span class="pm-pill" style="color:%s">'
            '%s</span></div><div class="d">%s</div><div class="m">%s<br>%s'
            '</div></div>' % (" hot" if hot else "", color, i + 1,
                              esc(title), scol, esc(status), esc(role),
                              esc(_agent_line(key, a)), esc(last_txt)))
        if i < len(AGENT_ROLES) - 1:
            parts.append('<div class="pm-arrow">▼</div>')
    st.markdown('<div class="pm-flow">%s</div>' % "".join(parts),
                unsafe_allow_html=True)
    st.caption("Durumlar controller'ın state.json çıktısından gelir; "
               "çerçeveli kart = son %d sn içinde olay üretti. Sistem "
               "kural tabanlıdır (yapay zekâ modeli yok)." % HOT_SEC)


STAGE_COLOR = {"done": COL["ok"], "skip": COL["muted"], "wait": COL["warn"],
               "fail": COL["warn"], "na": "#334155"}
STAGE_LABEL = {"done": "tamamlandı", "skip": "atlandı", "wait": "bekleniyor",
               "fail": "yol yok", "na": "uygulanmadı"}


def render_timeline(state, names):
    live_inc = active_incident(state)
    inc = live_inc or as_dict(state.get("latest_failure")) or None
    if not inc:
        st.markdown('<div class="pm-card"><div class="t">Self-healing '
                    'zaman çizelgesi</div><div style="padding:14px 0;color:'
                    '#8b9bb8">Henüz arıza olayı yok. GNS3\'te bir bağlantıyı '
                    'Suspend ettiğinizde tüm adımlar burada canlı görünür.'
                    '</div></div>', unsafe_allow_html=True)
        return
    live = live_inc is not None
    if live:
        badge = ('<span class="pm-badge" style="background:rgba(248,113,113,'
                 '.15);color:%s">● AKTİF ARIZA</span>' % COL["err"])
    else:
        badge = ('<span class="pm-badge" style="background:rgba(100,116,139,'
                 '.2);color:#94a3b8">GEÇMİŞ OLAY · %s</span>'
                 % esc(sr.ago(inc.get("started"))))
    stages = build_stages(state, inc, names, live)
    cells = []
    for i, (title, agent, stt, dt, detail) in enumerate(stages):
        c = STAGE_COLOR[stt]
        time_txt = ("+" + fmt_ms(dt)) if isinstance(dt, (int, float)) \
            else STAGE_LABEL[stt]
        cells.append(
            '<div class="pm-step" style="--c:%s"><div class="no">%d · %s'
            '</div><div class="t">%s</div><div class="a">%s</div>'
            '<div class="x">%s</div><div class="dd">%s</div></div>'
            % (c, i + 1, esc(STAGE_LABEL[stt]).upper(), esc(title),
               esc(agent), esc(time_txt), esc(detail)))
    notes = []
    inv = invalidation_note(state, inc)
    if inv:
        notes.append('<div class="pm-note">%s</div>' % esc(inv))
    if inc.get("recovery_ms") is not None:
        notes.append('<div class="pm-note">Kurtarma süresi: <b>%s</b> '
                     '(arıza algılandı → alternatif yol etkin). Bu, '
                     'controller içi tepki süresidir; uçtan uca paket '
                     'kaybı/gecikme ölçülmedi.</div>'
                     % esc(fmt_ms(inc["recovery_ms"])))
    st.markdown(
        '<div class="pm-card"><div class="t">Self-healing zaman çizelgesi '
        '· olay #%s%s</div><div style="margin:8px 0 10px 0;font-weight:700">'
        '%s · %s</div><div class="pm-steps">%s</div>%s</div>'
        % (esc(inc.get("id")), badge,
           esc(sr.pretty_link(inc.get("link"), names) if inc.get("link")
               else "port %s" % inc.get("port")),
           esc(clock(inc.get("started"))), "".join(cells), "".join(notes)),
        unsafe_allow_html=True)


def render_last_events(state, names):
    incs = as_list(state.get("incidents"))
    last = incs[-1] if incs else None
    rec = last_recovered(state)

    def card(title, body):
        return ('<div class="pm-card"><div class="t">%s</div>'
                '<div style="margin-top:6px">%s</div></div>'
                % (esc(title), body))

    if last:
        link = (sr.pretty_link(last.get("link"), names) if last.get("link")
                else "port %s" % last.get("port"))
        a = card("Son arıza (geçmiş kaydı)",
                 "<b>%s</b><br><span class='m' style='color:#8b9bb8'>"
                 "#%s · %s · %s · durum: %s</span>" % (
                     esc(link), esc(last.get("id")),
                     esc(clock(last.get("started"))),
                     esc(sr.ago(last.get("started"))),
                     esc(last.get("status"))))
    else:
        a = card("Son arıza", NO_DATA)
    if rec:
        path = sr.pretty_path(as_dict(rec.get("route")).get("path"), names)
        b = card("Son kurtarma (geçmiş kaydı)",
                 "<b>%s</b> · %s<br><span style='color:#8b9bb8'>#%s · %s · "
                 "%s · %s</span>" % (
                     esc(fmt_ms(rec.get("recovery_ms"))), esc(path or "-"),
                     esc(rec.get("id")), esc(clock(rec.get("started"))),
                     esc(sr.ago(rec.get("started"))),
                     esc(rec.get("status"))))
    else:
        b = card("Son kurtarma", "%s (henüz alternatif yol etkinleştirilen "
                 "olay yok)" % NO_DATA)
    st.markdown('<div style="display:grid;gap:12px;grid-template-columns:'
                '1fr 1fr;margin-top:12px">%s%s</div>' % (a, b),
                unsafe_allow_html=True)


# ----------------------------------------------------------------------
def render(state, status, names, inventory, topology_fn):
    """Sunum Modu ana ekranı (live_view fragment'i içinden çağrılır)."""
    render_kpis(state, status)
    left, right = st.columns([1.55, 1], gap="medium")
    with left:
        section("Canlı ağ topolojisi")
        fig = topology_fn(state, names, inventory, False, presentation=True)
        st.plotly_chart(fig, width="stretch", key="pm_topology",
                        config={"displayModeBar": False})
        st.caption("Mavi = çalışan bağlantı · kırmızı kesikli = kopmuş · "
                   "yeşil = aktif kurtarma yolu · p<n> = switch port "
                   "numarası. Bağlantılar controller tarafından dinamik "
                   "keşfedilir.")
    with right:
        section("Multi-Agent hattı")
        render_agents(state)
    section("Self-healing")
    render_timeline(state, names)
    render_last_events(state, names)
