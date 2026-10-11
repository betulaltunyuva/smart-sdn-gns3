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

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import DEAD_DISPATCHER
from os_ken.controller.handler import set_ev_cls
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
from utils.event_bus import EventBus, TOPO_LINK_ADDED, TOPO_LINK_REMOVED
from agents import (MonitoringAgent, FailureDetectionAgent, RoutingAgent,
                    RecoveryAgent)


class SDNController(app_manager.OSKenApp):
    """Basit OpenFlow 1.3 MAC-learning switch uygulaması."""

    # Yalnızca OpenFlow 1.3 kabul edilir
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

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
    # Yardımcı: flow ekleme
    # ------------------------------------------------------------------
    def add_flow(self, datapath, priority, match, actions, buffer_id=None,
                 idle_timeout=0, hard_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        kwargs = dict(datapath=datapath, priority=priority, match=match,
                      instructions=inst, idle_timeout=idle_timeout,
                      hard_timeout=hard_timeout)
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

        self.logger.info("PacketIn: DPID=%016x src=%s dst=%s in_port=%s",
                         dpid, src, dst, in_port)

        # Kaynak MAC adresini öğren
        self.mac_to_port[dpid][src] = in_port

        # Hedef port biliniyorsa oraya, değilse flood
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Hedef biliniyorsa flow ekle (sonraki paketler controller'a gelmez)
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(datapath, 1, match, actions, msg.buffer_id,
                          idle_timeout=60)
            self.logger.info("Flow eklendi: DPID=%016x %s -> %s out_port=%s",
                             dpid, src, dst, out_port)
            # Paket switch'te buffer'landıysa flow-mod onu zaten iletir
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                return

        # Paketi switch'e geri gönder (PacketOut)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
