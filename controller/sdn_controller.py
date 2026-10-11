"""
Smart SDN (GNS3) - OS-Ken OpenFlow 1.3 Learning Switch Controller
  - Aşama 3  : OpenFlow 1.3 learning switch
  - Aşama 4.1: Dinamik switch discovery (DPID bazlı aktif switch takibi)
  - Aşama 4.2: LLDP tabanlı dinamik link discovery (os_ken.topology)
  - Aşama 4.3: Switch/linklerden NetworkX graph (topology/topology_manager.py)
  - Aşama 5.1: Graph üzerinden dinamik shortest path (yalnızca loglama)
  - Aşama 6  : Multi-agent iskeleti (agents/, utils/event_bus.py)
               LINK_ADDED/LINK_REMOVED -> Monitoring -> Failure -> Routing
               -> Recovery (yalnızca loglama, flow kurulmaz)
  - Aşama 6.2: Periyodik OpenFlow 1.3 port istatistikleri
               (PortDesc + PortStats) -> MonitoringAgent metrikleri

GNS3 içindeki Open vSwitch node'ları ile çalışmak üzere tasarlanmıştır.
Yalnızca OpenFlow 1.3 destekler.

Çalıştırma (link discovery için --observe-links ZORUNLU):
    osken-manager --observe-links controller/sdn_controller.py

--observe-links verilmezse os_ken.topology.switches LLDP göndermez ve
EventLinkAdd/EventLinkDelete hiç üretilmez (switch discovery yine çalışır).

OVS tarafında (GNS3 Open vSwitch node'u içinde) örnek ayar:
    ovs-vsctl set bridge br0 protocols=OpenFlow13
    ovs-vsctl set-controller br0 tcp:<CONTROLLER_IP>:6653
"""

import logging
import os
import sys
import time

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import DEAD_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ether_types
from os_ken.ofproto import ofproto_v1_3
# os_ken.topology.event import edildiğinde os_ken.topology.switches uygulaması
# otomatik yüklenir (LLDP gönderimi/alımı ve link takibi orada yapılır).
from os_ken.topology import event as topo_event

# osken-manager bu dosyayı yol ile yüklediğinden proje kökü sys.path'te
# değildir; topology paketini import edebilmek için eklenir.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# NetworkX yoksa graph devre dışı kalır; learning switch ve discovery
# çalışmaya devam eder.
try:
    from topology.topology_manager import TopologyManager
    _TOPOLOGY_IMPORT_ERROR = None
except ImportError as e:
    TopologyManager = None
    _TOPOLOGY_IMPORT_ERROR = e

# Aşama 6: multi-agent iskeleti (yalnızca standart kütüphane kullanır)
from utils.event_bus import (EventBus, TOPO_LINK_ADDED, TOPO_LINK_REMOVED,
                             TOPO_SWITCH_REMOVED, PORT_STATUS_UPDATE,
                             PORT_STATS_UPDATE)
from agents import (MonitoringAgent, FailureDetectionAgent, RoutingAgent,
                    RecoveryAgent)


class SDNController(app_manager.OSKenApp):
    """Basit OpenFlow 1.3 MAC-learning switch uygulaması."""

    # Yalnızca OpenFlow 1.3 kabul edilir
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # Aşama 6.2: port istatistik sorgulama aralığı (saniye)
    STATS_INTERVAL = 5

    # MAC learning ile kurulan flowların cookie'si: topoloji değişince
    # yalnızca bu flowlar silinir (table-miss ve LLDP flowlarına dokunulmaz)
    LEARNED_FLOW_COOKIE = 0x5D

    def __init__(self, *args, **kwargs):
        super(SDNController, self).__init__(*args, **kwargs)
        # osken-manager varsayılan olarak yalnızca WARNING loglarını gösterir;
        # bu uygulamanın INFO loglarının --verbose olmadan da görünmesi için:
        self.logger.setLevel(logging.INFO)
        # MAC tablosu: {dpid: {mac_adresi: port_no}}
        self.mac_to_port = {}
        # Aktif switchler: {dpid: datapath}
        # Sabit liste yok; switchler OpenFlow bağlantı eventleriyle eklenir/çıkarılır.
        self.datapaths = {}
        # Aktif linkler (Aşama 4.2). OS-Ken her fiziksel linki iki yönlü
        # (A->B ve B->A) ayrı ayrı raporlar; bu yüzden iki yapı tutulur:
        #   link_directions: OS-Ken'in bildirdiği aktif yönlü linkler
        #       {(src_dpid, src_port, dst_dpid, dst_port), ...}
        #   links: fiziksel (yönsüz) linkler, her biri tek kayıt
        #       {((dpid_a, port_a), (dpid_b, port_b)): {"src_dpid": ...,
        #         "src_port": ..., "dst_dpid": ..., "dst_port": ...}}
        #       Anahtar uç noktaların sıralanmış hali olduğundan A->B ve
        #       B->A aynı anahtara düşer.
        # Sabit DPID/port/link listesi yok; tamamen eventlerle doldurulur.
        self.link_directions = set()
        self.links = {}
        # Döngüsüz flood (broadcast storm / MAC flapping önleme). self.links
        # üzerinden hesaplanan spanning tree'ye göre:
        #   isl_ports:  {dpid: {port, ...}} switchler arası (LLDP) portlar
        #   tree_ports: {dpid: {port, ...}} spanning tree'deki ISL portları
        # Tree dışındaki ISL portlarından flood yapılmaz, gelen flood/öğrenme
        # paketleri düşürülür.
        self.isl_ports = {}
        self.tree_ports = {}
        # Topoloji graph'ı (Aşama 4.3): self.datapaths ve self.links'ten
        # türetilir, her switch/link değişikliğinde senkronize edilir.
        self.topology = None
        if TopologyManager is not None:
            self.topology = TopologyManager(logger=self.logger)
        # Multi-agent zinciri (Aşama 6). Agentlar yalnızca EventBus
        # üzerinden haberleşir; RoutingAgent yukarıdaki aynı TopologyManager
        # örneğini (canlı graph) kullanır.
        self.event_bus = EventBus(logger=self.logger)
        self.monitoring_agent = MonitoringAgent(self.event_bus, self.logger)
        self.failure_agent = FailureDetectionAgent(self.event_bus,
                                                   self.logger)
        self.routing_agent = RoutingAgent(self.event_bus, self.topology,
                                          self.logger)
        self.recovery_agent = RecoveryAgent(self.event_bus, self.logger)
        # Aşama 6.2: aktif switchlerden periyodik port istatistiği iste
        self.stats_thread = hub.spawn(self._stats_loop)
        self.logger.info("SDN Controller başlatıldı (OpenFlow 1.3)")
        if self.topology is None:
            self.logger.warning("Topoloji graph KAPALI (%s); kurulum: "
                                "sudo apt install python3-networkx",
                                _TOPOLOGY_IMPORT_ERROR)
        if not getattr(self.CONF, 'observe_links', False):
            self.logger.warning("Link discovery KAPALI: osken-manager "
                                "--observe-links ile başlatılmalı")

    # ------------------------------------------------------------------
    # Switch bağlantısı: table-miss flow kurulumu
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.logger.info("Switch bağlandı: DPID=%016x", datapath.id)

        # Table-miss flow: eşleşmeyen tüm paketleri controller'a gönder.
        # OFPCML_NO_BUFFER ile paketin tamamı controller'a iletilir.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Table-miss flow eklendi: DPID=%016x", datapath.id)

        # Features reply alındığında DPID kesin olarak bilinir. OF1.3'te
        # MAIN_DISPATCHER'a geçiş ayrıca PortDesc cevabına bağlı olduğundan,
        # gerçek switchlerde discovery bu adımda da kaydedilir (duplicate yok).
        self._register_switch(datapath)

    # ------------------------------------------------------------------
    # Switch discovery: bağlantı durumu değişikliklerini takip et
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath

        if ev.state == MAIN_DISPATCHER:
            # Handshake tamamlandı: switch aktif
            self._register_switch(datapath)
        elif ev.state == DEAD_DISPATCHER:
            self._unregister_switch(datapath)

    # ------------------------------------------------------------------
    # Aktif switch listesi (tek doğru kaynak: self.datapaths)
    # ------------------------------------------------------------------
    def _register_switch(self, datapath):
        dpid = datapath.id
        # Handshake tamamlanmadan DPID bilinmeyebilir
        if dpid is None:
            return
        # Aynı bağlantı zaten kayıtlıysa tekrar SWITCH_ADDED üretme
        if self.datapaths.get(dpid) is datapath:
            return
        # Aynı DPID yeni bir bağlantıyla geldiyse eski kaydın yerine geçer
        self.datapaths[dpid] = datapath
        self.logger.info("SWITCH_ADDED DPID=%016x "
                         "toplam aktif switch sayısı=%d",
                         dpid, len(self.datapaths))
        self._update_topology()

    def _unregister_switch(self, datapath):
        dpid = datapath.id
        # Handshake tamamlanmadan kopan bağlantıların DPID'si olmayabilir
        if dpid is None:
            return
        # Aynı DPID yeniden bağlandıysa eski bağlantının kapanması
        # yeni (aktif) kaydı silmesin
        if self.datapaths.get(dpid) is not datapath:
            return
        del self.datapaths[dpid]
        # Kopan switch'e ait öğrenilmiş MAC bilgisi artık geçersiz
        self.mac_to_port.pop(dpid, None)
        self.logger.info("SWITCH_REMOVED DPID=%016x "
                         "toplam aktif switch sayısı=%d",
                         dpid, len(self.datapaths))
        self._update_topology()
        self.event_bus.publish(TOPO_SWITCH_REMOVED, {"dpid": dpid})

    # ------------------------------------------------------------------
    # Link discovery (LLDP): os_ken.topology.switches eventleri
    # ------------------------------------------------------------------
    @staticmethod
    def _link_tuple(link):
        return (link.src.dpid, link.src.port_no,
                link.dst.dpid, link.dst.port_no)

    @staticmethod
    def _link_key(src_dpid, src_port, dst_dpid, dst_port):
        # Yönsüz anahtar: A->B ve B->A aynı fiziksel linki temsil eder
        return tuple(sorted(((src_dpid, src_port), (dst_dpid, dst_port))))

    @set_ev_cls(topo_event.EventLinkAdd)
    def link_add_handler(self, ev):
        direction = self._link_tuple(ev.link)
        if direction in self.link_directions:
            return
        self.link_directions.add(direction)

        key = self._link_key(*direction)
        # Ters yön daha önce görüldüyse fiziksel link zaten kayıtlı:
        # tekrar LINK_ADDED üretme
        if key in self.links:
            return
        src_dpid, src_port, dst_dpid, dst_port = direction
        self.links[key] = {"src_dpid": src_dpid, "src_port": src_port,
                           "dst_dpid": dst_dpid, "dst_port": dst_port}
        self.logger.info("LINK_ADDED src_dpid=%016x src_port=%s "
                         "dst_dpid=%016x dst_port=%s "
                         "toplam aktif link sayısı=%d",
                         src_dpid, src_port, dst_dpid, dst_port,
                         len(self.links))
        self._update_topology()
        self.event_bus.publish(TOPO_LINK_ADDED, dict(self.links[key]))

    @set_ev_cls(topo_event.EventLinkDelete)
    def link_delete_handler(self, ev):
        direction = self._link_tuple(ev.link)
        if direction not in self.link_directions:
            return
        self.link_directions.discard(direction)

        src_dpid, src_port, dst_dpid, dst_port = direction
        key = self._link_key(*direction)
        # Ters yön hâlâ aktifse fiziksel link henüz tamamen kalkmadı;
        # OS-Ken onu da kısa sürede (port down / LLDP timeout) siler.
        if (dst_dpid, dst_port, src_dpid, src_port) in self.link_directions:
            return
        info = self.links.pop(key, None)
        if info is None:
            return
        self.logger.info("LINK_REMOVED src_dpid=%016x src_port=%s "
                         "dst_dpid=%016x dst_port=%s "
                         "toplam aktif link sayısı=%d",
                         info["src_dpid"], info["src_port"],
                         info["dst_dpid"], info["dst_port"],
                         len(self.links))
        self._update_topology()
        # Graph güncellendikten SONRA agent zinciri tetiklenir; böylece
        # RoutingAgent arızalı linkin çıkarıldığı graph üzerinde hesap yapar.
        self.event_bus.publish(TOPO_LINK_REMOVED, dict(info))

    # ------------------------------------------------------------------
    # Topoloji graph güncelleme (Aşama 4.3)
    # ------------------------------------------------------------------
    def _update_topology(self):
        self._update_flood_tree()
        if self.topology is None:
            return
        if self.topology.sync(self.datapaths, self.links):
            self.topology.log_graph()
            self._log_shortest_paths()

    def _log_shortest_paths(self):
        """Test amaçlı: graph her değiştiğinde aktif switch çiftleri arası
        shortest path'i loglar. DPID'ler graph'tan okunur (sabit DPID yok).
        Yalnızca log üretir; flow kurallarına dokunmaz."""
        dpids = sorted(self.topology.graph.nodes)
        for i, src in enumerate(dpids):
            for dst in dpids[i + 1:]:
                self.topology.get_shortest_path(src, dst)

    # ------------------------------------------------------------------
    # Döngüsüz flood için spanning tree (MAC learning düzeltmesi)
    # ------------------------------------------------------------------
    def _update_flood_tree(self):
        """self.links'ten deterministik bir spanning tree (Kruskal) hesaplar.
        Redundant linkli topolojide OFPP_FLOOD broadcast'i döngüye sokar ve
        host MAC'leri switchler arası portlarda (yanlış portta) öğrenilir.
        Tree değişirse öğrenilmiş MAC tablosu ve learning flowları silinir."""
        parent = {dpid: dpid for dpid in self.datapaths}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        isl_ports = {}
        tree_ports = {}
        for key in sorted(self.links):
            (a, pa), (b, pb) = key
            if a not in parent or b not in parent:
                continue
            isl_ports.setdefault(a, set()).add(pa)
            isl_ports.setdefault(b, set()).add(pb)
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
                tree_ports.setdefault(a, set()).add(pa)
                tree_ports.setdefault(b, set()).add(pb)

        if isl_ports == self.isl_ports and tree_ports == self.tree_ports:
            return
        self.isl_ports = isl_ports
        self.tree_ports = tree_ports
        self.logger.info("Flood tree güncellendi: tree_ports=%s "
                         "bloklu_isl_ports=%s",
                         {"%016x" % d: sorted(p) for d, p in tree_ports.items()},
                         {"%016x" % d: sorted(p - tree_ports.get(d, set()))
                          for d, p in isl_ports.items()
                          if p - tree_ports.get(d, set())})
        # Eski topolojide öğrenilen portlar artık yanlış olabilir
        self.mac_to_port.clear()
        for datapath in list(self.datapaths.values()):
            self._delete_learned_flows(datapath)

    def _delete_learned_flows(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, cookie=self.LEARNED_FLOW_COOKIE,
            cookie_mask=0xffffffffffffffff, table_id=ofproto.OFPTT_ALL,
            command=ofproto.OFPFC_DELETE, out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY, match=parser.OFPMatch()))

    def _is_blocked_port(self, dpid, port_no):
        """Spanning tree dışında kalan switchler arası port mu?"""
        return (port_no in self.isl_ports.get(dpid, ())
                and port_no not in self.tree_ports.get(dpid, ()))

    def _flood_actions(self, datapath, in_port):
        """in_port ve bloklu ISL portları hariç tüm veri portlarına çıkış.
        Port listesi switch'in kendi PortDesc bilgisinden gelir."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        ports = getattr(datapath, "ports", None) or {}
        if not ports:
            # Port listesi henüz yoksa eski davranış
            return [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        return [parser.OFPActionOutput(p) for p in sorted(ports)
                if self._is_data_port(ofproto, p) and p != in_port
                and not self._is_blocked_port(datapath.id, p)]

    # ------------------------------------------------------------------
    # Port istatistikleri (Aşama 6.2)
    # ------------------------------------------------------------------
    def _stats_loop(self):
        """Her STATS_INTERVAL saniyede aktif switchlere PortDesc ve
        PortStats isteği gönderir. hub.sleep ile bekler (busy loop yok);
        cevaplar aşağıdaki handler'larda asenkron işlenir."""
        while True:
            for datapath in list(self.datapaths.values()):
                try:
                    self._request_port_stats(datapath)
                except Exception:
                    self.logger.exception("Port stats isteği gönderilemedi "
                                          "DPID=%016x", datapath.id)
            hub.sleep(self.STATS_INTERVAL)

    @staticmethod
    def _request_port_stats(datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        # Önce port durumu, sonra sayaçlar: aynı TCP bağlantısında sırayla
        # işlendiğinden metrik logunda güncel port durumu kullanılır.
        datapath.send_msg(parser.OFPPortDescStatsRequest(datapath, 0))
        datapath.send_msg(parser.OFPPortStatsRequest(datapath, 0,
                                                     ofproto.OFPP_ANY))

    @staticmethod
    def _is_data_port(ofproto, port_no):
        # LOCAL, CONTROLLER vb. ayrılmış OpenFlow portları hariç tutulur
        return port_no <= ofproto.OFPP_MAX

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        # Yalnızca aktif (kayıtlı) switchlerin cevapları işlenir
        if self.datapaths.get(datapath.id) is not datapath:
            return
        ports = []
        for p in ev.msg.body:
            if not self._is_data_port(ofproto, p.port_no):
                continue
            name = p.name
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            ports.append({
                "port_no": p.port_no,
                "name": name.rstrip("\x00"),
                "link_up": not (p.state & ofproto.OFPPS_LINK_DOWN),
                "admin_up": not (p.config & ofproto.OFPPC_PORT_DOWN)})
        self.event_bus.publish(PORT_STATUS_UPDATE,
                               {"dpid": datapath.id, "ports": ports})

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        timestamp = time.monotonic()
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        if self.datapaths.get(datapath.id) is not datapath:
            return
        ports = []
        for s in ev.msg.body:
            if not self._is_data_port(ofproto, s.port_no):
                continue
            ports.append({
                "port_no": s.port_no,
                "rx_bytes": s.rx_bytes, "tx_bytes": s.tx_bytes,
                "rx_packets": s.rx_packets, "tx_packets": s.tx_packets,
                "rx_errors": s.rx_errors, "tx_errors": s.tx_errors,
                "rx_dropped": s.rx_dropped, "tx_dropped": s.tx_dropped,
                "duration_sec": getattr(s, "duration_sec", None),
                "duration_nsec": getattr(s, "duration_nsec", 0)})
        self.event_bus.publish(PORT_STATS_UPDATE,
                               {"dpid": datapath.id, "timestamp": timestamp,
                                "ports": ports})

    # ------------------------------------------------------------------
    # Yardımcı: flow ekleme
    # ------------------------------------------------------------------
    def add_flow(self, datapath, priority, match, actions, buffer_id=None,
                 idle_timeout=0, hard_timeout=0, cookie=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        kwargs = dict(datapath=datapath, priority=priority, match=match,
                      instructions=inst, idle_timeout=idle_timeout,
                      hard_timeout=hard_timeout, cookie=cookie)
        if buffer_id is not None and buffer_id != ofproto.OFP_NO_BUFFER:
            kwargs['buffer_id'] = buffer_id
        datapath.send_msg(parser.OFPFlowMod(**kwargs))

    # ------------------------------------------------------------------
    # PacketIn: MAC learning ve iletim
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # LLDP paketlerini yok say: link discovery'yi os_ken.topology.switches
        # yapar; LLDP kullanıcı trafiği gibi öğrenilmez/forward edilmez
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        # Spanning tree dışındaki switchler arası porttan gelen paket bir
        # döngü kopyasıdır: öğrenilmez, iletilmez
        if self._is_blocked_port(dpid, in_port):
            return
        # Multicast/broadcast kaynak MAC geçersizdir; öğrenilmez
        if int(src.split(':')[0], 16) & 1:
            return

        self.logger.info("PacketIn: DPID=%016x src=%s dst=%s in_port=%s",
                         dpid, src, dst, in_port)

        # Kaynak MAC adresini (bu switch için) giriş portunda öğren
        self.mac_to_port[dpid][src] = in_port

        # Hedef port biliniyorsa oraya, değilse flood (döngüsüz)
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
            if out_port == in_port:
                # Hedef paketin geldiği tarafta: geri gönderilmez ve
                # giriş=çıkış portlu (hairpin) flow asla kurulmaz
                self.logger.info("Hairpin engellendi: DPID=%016x %s -> %s "
                                 "port=%s", dpid, src, dst, in_port)
                return
            actions = [parser.OFPActionOutput(out_port)]
        else:
            out_port = ofproto.OFPP_FLOOD
            actions = self._flood_actions(datapath, in_port)

        # Hedef biliniyorsa flow ekle (sonraki paketler controller'a gelmez)
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(datapath, 1, match, actions, msg.buffer_id,
                          idle_timeout=60, cookie=self.LEARNED_FLOW_COOKIE)
            self.logger.info("Flow eklendi: DPID=%016x %s -> %s out_port=%s",
                             dpid, src, dst, out_port)
            # Paket switch'te buffer'landıysa flow-mod onu zaten iletir
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                return

        if not actions:
            return

        # Paketi switch'e geri gönder (PacketOut)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
