# Multi-Agent Tabanlı Akıllı Self-Healing SDN

## Proje Hakkında

Bu proje, **GNS3 üzerinde gerçekçi bir kurumsal/kampüs ağı oluşturarak Software-Defined Networking (SDN), Multi-Agent sistemler, ağ izleme, otomatik hata tespiti, dinamik routing ve self-healing mekanizmalarını tek bir sistemde birleştirmeyi** amaçlamaktadır.

Proje ilk olarak daha küçük bir SDN laboratuvar topolojisi üzerinde geliştirilmiştir. Bu ilk yapı üzerinde:

- dinamik switch keşfi,
- dinamik link keşfi,
- NetworkX tabanlı graph oluşturma,
- shortest-path hesaplama,
- Monitoring Agent,
- Failure Detection Agent,
- Routing Agent,
- Recovery Agent,
- startup otomasyonu,
- runtime state,
- Streamlit dashboard

gibi temel bileşenler geliştirilmiştir.

Daha sonra sistem, daha gerçekçi bir kurumsal ağ ortamında test edilmek üzere:

`Smart_SDN_MultiAgent_v2_Work`

topolojisine taşınmış ve ağ; VLAN, access/distribution katmanları, sunucular, NAT, firewall ve servisler ile genişletilmiştir.

---

# Güncel Durum

> **27 Ekim 2026 itibarıyla Aşama 0–6 tamamlanmıştır.**
>
> **Sıradaki aşama: Aşama 7 — Multi-Agent Entegrasyonu**

Şu ana kadar başarıyla tamamlanan ana çalışmalar:

- Çalışan eski SDN sürümünün korunması
- Yeni kurumsal GNS3 topolojisinin oluşturulması
- Access ve Distribution katmanlarının eklenmesi
- Kullanıcı gruplarının ayrılması
- VLAN mimarisinin oluşturulması
- Router-on-a-Stick yapılandırması
- VLAN'lar arası routing
- NAT ve internet erişimi
- Stateful firewall
- Rol bazlı erişim politikaları
- WEB-SERVER
- DNS-SERVER
- DB-SERVER
- Yerel DNS çözümleme
- WEB → DB gerçek MariaDB bağlantısı
- Servis ve ağ yapılandırmalarının kalıcı hale getirilmesi
- Open vSwitch cihazlarının SDN omurgası olarak konumlandırılması
- 4 OVS'in OS-Ken controller'a bağlanması
- OpenFlow 1.3 doğrulaması
- Dinamik switch keşfi
- LLDP tabanlı dinamik link keşfi
- NetworkX graph oluşturma
- Dinamik shortest-path hesaplama
- Kontrollü link failure testi
- Alternatif yol oluşturma
- Recovery flow'larının yüklenmesi
- Link arızası sırasında gerçek trafiğin devam etmesi
- Link geri geldiğinde topolojinin otomatik güncellenmesi

---

# 1. Kullanılan Teknolojiler

Projede kullanılan başlıca teknolojiler:

- **GNS3**
- **Open vSwitch (OVS)**
- **OpenFlow 1.3**
- **OS-Ken Controller**
- **Python**
- **NetworkX**
- **Multi-Agent mimari**
- **Event-driven haberleşme**
- **Docker tabanlı GNS3 düğümleri**
- **VLAN**
- **nftables**
- **dnsmasq**
- **lighttpd**
- **MariaDB**
- **Streamlit**
- **Git / GitHub**

---

# 2. Güncel Ağ Mimarisi

Yeni ağ, küçük SDN laboratuvar ortamından daha gerçekçi bir **kurumsal/kampüs ağı** modeline dönüştürülmüştür.

Ağ temel olarak şu katmanlardan oluşmaktadır:

```text
                    INTERNET
                       |
                    ROUTER-1
                       |
        --------------------------------
        |                              |
   Kurumsal Ağ                    SDN Omurgası
        |                              |
 Access / Distribution          Open vSwitch
        |                              |
 Kullanıcı VLAN'ları             OS-Ken Controller
        |
 SERVER VLAN
        |
 WEB / DNS / DB
```

---

# 3. VLAN ve Kullanıcı Grupları

Kullanıcı grupları birbirinden mantıksal olarak ayrılmıştır.

| VLAN | Rol | Ağ |
|---|---|---|
| VLAN 10 | ADMIN | `10.10.10.0/24` |
| VLAN 20 | STAFF | `10.10.20.0/24` |
| VLAN 30 | GUEST | `10.10.30.0/24` |
| VLAN 40 | STUDENT | `10.10.40.0/24` |
| VLAN 50 | SERVER | `10.10.50.0/24` |

ROUTER-1 üzerindeki gateway adresleri:

```text
VLAN 10 → 10.10.10.1
VLAN 20 → 10.10.20.1
VLAN 30 → 10.10.30.1
VLAN 40 → 10.10.40.1
VLAN 50 → 10.10.50.1
```

---

# 4. Kullanıcı Uç Cihazları

## ADMIN

```text
ADMIN-PC1
ADMIN-PC2
```

ADMIN cihazları VLAN 10 içerisindedir.

Yönetim ağı olarak diğer kullanıcı gruplarına göre daha geniş erişim yetkisine sahiptir.

## STAFF

```text
STAFF-PC1
STAFF-PC2
```

STAFF cihazları VLAN 20 içerisindedir.

Personel ağı sunucu hizmetlerine ve internete erişebilir ancak diğer kullanıcı VLAN'larından izole edilmiştir.

## GUEST

```text
GUEST-PC1
GUEST-PC2
```

GUEST cihazları VLAN 30 içerisindedir.

Misafir kullanıcılar:

- internete erişebilir,
- DNS hizmetini kullanabilir,
- diğer kurumsal kullanıcı ağlarına doğrudan erişemez.

## STUDENT

```text
STUDENT-PC1
STUDENT-PC2
```

STUDENT cihazları VLAN 40 içerisindedir.

Öğrenci ağı:

- sunucu hizmetlerine erişebilir,
- internete erişebilir,
- ADMIN, STAFF ve GUEST ağlarından izole edilmiştir.

---

# 5. Access ve Distribution Katmanı

Kullanıcı cihazlarının doğrudan SDN omurgasına bağlanması yerine gerçek kurumsal ağlara daha yakın bir yapı oluşturulmuştur.

Access switch'ler:

```text
ACCESS-SW1
ACCESS-SW2
ACCESS-SW3
ACCESS-SW4
```

Distribution switch'ler:

```text
DIST-SW1
DIST-SW2
```

Access ve Distribution katmanlarında normal Ethernet switch'ler kullanılmaktadır.

Open vSwitch cihazları ise yalnızca SDN kontrolünün gerekli olduğu omurga bölümünde tutulmaktadır.

---

# 6. Router-on-a-Stick

ROUTER-1 üzerinde VLAN alt arayüzleri kullanılarak Router-on-a-Stick mimarisi uygulanmıştır.

Örnek alt arayüzler:

```text
eth0.10
eth0.20
eth0.30
eth0.40
eth0.50
```

Bu yapı sayesinde farklı VLAN'lar arasında kontrollü Layer-3 routing yapılabilmektedir.

---

# 7. ROUTER-1

ROUTER-1 ağın merkezi Layer-3 bileşenidir.

Başlıca görevleri:

- VLAN gateway'lerini sağlamak
- VLAN'lar arasında routing yapmak
- internet erişimini yönetmek
- NAT uygulamak
- firewall politikalarını uygulamak
- SERVER VLAN'a erişimi kontrol etmek

Projede ayrı bir firewall appliance kullanılmamaktadır.

Firewall fonksiyonu ROUTER-1 üzerinde **nftables** ile uygulanmıştır.

---

# 8. NAT ve İnternet Erişimi

İç ağların dış ağa erişebilmesi için ROUTER-1 üzerinde nftables tabanlı NAT yapılandırılmıştır.

NAT kapsamındaki ağlar:

```text
10.10.10.0/24
10.10.20.0/24
10.10.30.0/24
10.10.40.0/24
10.10.50.0/24
```

İç ağ trafiği dış arayüz üzerinden masquerade edilmektedir.

İlgili dosyalar:

```text
configs/router/nat.nft
configs/router/nat.sh
```

NAT yapılandırmasının GNS3 Stop → Start işlemi sonrasında yeniden çalıştığı doğrulanmıştır.

---

# 9. Stateful Firewall

ROUTER-1 üzerinde nftables tabanlı stateful firewall bulunmaktadır.

Mevcut bağlantılara ait dönüş paketleri:

```text
ct state established,related accept
```

mantığıyla kabul edilmektedir.

Böylece yalnızca kaynak/hedef IP bazlı filtreleme yerine bağlantının durumunu takip eden stateful güvenlik politikaları uygulanmaktadır.

İlgili dosyalar:

```text
configs/router/filter.nft
configs/router/filter.sh
```

---

# 10. Rol Bazlı Ağ Politikaları

Ağ grupları arasında erişim kontrolü uygulanmaktadır.

## ADMIN

Yönetim ağıdır ve gerekli iç ağlara erişim yetkisine sahiptir.

## STAFF

```text
SERVER   → izinli
Internet → izinli
```

Diğer kullanıcı VLAN'larına doğrudan erişim sınırlandırılmıştır.

## STUDENT

```text
SERVER   → izinli
Internet → izinli
```

ADMIN, STAFF ve GUEST ağlarından izole edilmiştir.

## GUEST

```text
Internet → izinli
DNS      → izinli
```

Diğer kurumsal kullanıcı ağlarına erişim engellenmiştir.

Politikalar gerçek VPCS cihazlarından yapılan bağlantı testleriyle doğrulanmıştır.

---

# 11. SERVER VLAN

Sunucular için ayrı bir ağ segmenti oluşturulmuştur.

```text
VLAN 50
10.10.50.0/24
```

Bu bölüm korumalı sunucu bölgesi olarak kullanılmaktadır.

Sunucular:

```text
WEB-SERVER
DNS-SERVER
DB-SERVER
```

---

# 12. WEB-SERVER

WEB-SERVER IP adresi:

```text
10.10.50.10
```

Web servisi:

```text
lighttpd
```

ile çalışmaktadır.

Test web sayfası:

```text
Smart SDN Network
WEB-SERVER is running successfully.
IP: 10.10.50.10
```

şeklinde yanıt vermektedir.

Yerel DNS kaydı:

```text
web.sdn.test → 10.10.50.10
```

Kalıcı WEB yapılandırmaları:

```text
configs/web/
```

altında tutulmaktadır.

---

# 13. DNS-SERVER

DNS-SERVER IP adresi:

```text
10.10.50.53
```

DNS hizmeti:

```text
dnsmasq
```

ile sağlanmaktadır.

Yerel kayıtlar:

```text
web.sdn.test → 10.10.50.10
db.sdn.test  → 10.10.50.20
```

DNS-SERVER'ın hem yerel isimleri hem de dış internet alan adlarını çözebildiği doğrulanmıştır.

İlgili yapılandırmalar:

```text
configs/dns/
```

altındadır.

---

# 14. DB-SERVER

DB-SERVER IP adresi:

```text
10.10.50.20
```

Veritabanı sistemi:

```text
MariaDB 11.8.9
```

Projeye ait veritabanı:

```text
smart_sdn
```

Test tablosu:

```text
network_status
```

Örnek kayıt:

```text
DB-SERVER | ACTIVE
```

---

# 15. WEB → DB Bağlantısı

WEB-SERVER'ın DB-SERVER'a gerçek MariaDB bağlantısı kurabildiği doğrulanmıştır.

Bağlantı zinciri:

```text
WEB-SERVER
    |
    v
db.sdn.test
    |
    v
DNS-SERVER
    |
    v
10.10.50.20
    |
    v
TCP/3306
    |
    v
MariaDB
    |
    v
smart_sdn
```

WEB-SERVER üzerinden:

```sql
SELECT * FROM network_status;
```

sorgusu çalıştırılmış ve:

```text
DB-SERVER | ACTIVE
```

sonucu alınmıştır.

Bu test tek seferde:

- DNS çözümleme,
- WEB → DB iletişimi,
- TCP/3306 erişimi,
- MariaDB kullanıcı yetkisi,
- veritabanı erişimi,
- tablo erişimi,
- veri erişimi

bileşenlerini doğrulamaktadır.

> Veritabanı parolaları ve diğer hassas bilgiler GitHub repository'sinde tutulmamaktadır.

---

# 16. Kalıcılık

GNS3 Docker düğümlerinde runtime değişikliklerinin yeniden başlatma sonrasında kaybolabilmesi nedeniyle kritik servisler için kalıcılık mekanizmaları hazırlanmıştır.

Kalıcı hale getirilen bileşenler arasında:

- Router IP yapılandırmaları
- VLAN gateway'leri
- NAT
- firewall
- DNS yapılandırması
- WEB-SERVER yapılandırması
- DB-SERVER IP yapılandırması
- MariaDB paketleri
- MariaDB veri dizini
- MariaDB startup scripti
- WEB startup scripti
- DNS startup scripti

bulunmaktadır.

DB-SERVER Stop → Start sonrasında:

```text
10.10.50.20
MariaDB
smart_sdn
network_status
DB-SERVER | ACTIVE
```

bilgilerinin korunduğu doğrulanmıştır.

---

# 17. SDN Omurgası

Aşama 5 kapsamında SDN switch stratejisi kesinleştirilmiştir.

SDN omurgasında dört Open vSwitch kullanılmaktadır:

```text
        OVS-1
       /     \
    OVS-3   OVS-2
       \     /
        OVS-4
```

Canlı topolojide fiziksel bağlantı/port eşleşmeleri çalışma anında keşfedildiği için routing kodunda sabit switch yolu kullanılmamaktadır.

Access, Distribution ve Server taraflarında normal Ethernet switch'ler bulunurken OVS cihazları SDN kontrollü omurga olarak kullanılmaktadır.

Bu sayede SDN kontrolü yalnızca gerekli noktalarda tutulmaktadır.

---

# 18. OpenFlow ve OS-Ken Controller

Controller dosyası:

```text
controller/sdn_controller.py
```

Kullanılan OpenFlow sürümü:

```text
OpenFlow 1.3
```

Controller endpoint'i:

```text
tcp:192.168.122.1:6653
```

OVS tarafında:

```text
br0
OpenFlow13
fail-mode=secure
```

yapısı kullanılmaktadır.

Aşama 5 doğrulamasında dört OVS'in de controller'a başarıyla bağlandığı görülmüştür.

---

# 19. OVS Management Ağı

`start_sdn.sh` scripti çalışan GNS3 Open vSwitch container'larını otomatik olarak keşfetmektedir.

Management interface sabit bir port adına bağlı değildir.

Script:

1. çalışan OVS container'ını bulur,
2. kullanılabilir management portunu belirler,
3. management IP'sini alır,
4. controller adresini ayarlar,
5. OpenFlow 1.3 protokolünü ayarlar,
6. `fail-mode=secure` durumunu doğrular.

Management IP adresleri çalışma ortamına göre değişebildiği için README içerisinde sabit OVS management IP'leri tutulmamaktadır.

---

# 20. Dinamik Switch Keşfi

Controller switch'leri önceden sabit olarak tanımlamaz.

OpenFlow bağlantısı kuran switch'ler DPID üzerinden çalışma anında keşfedilir.

Aşama 6 testinde:

```text
Aktif switch sayısı = 4
```

olarak doğrulanmıştır.

Her OVS'in benzersiz bir DPID ile controller'a bağlandığı görülmüştür.

---

# 21. Dinamik Link Keşfi

OS-Ken:

```text
--observe-links
```

özelliğiyle başlatılmaktadır.

Bu sayede LLDP kullanılarak OVS'ler arasındaki bağlantılar otomatik keşfedilmektedir.

Aşama 6 başlangıç durumunda:

```text
Aktif link sayısı = 4
```

olarak doğrulanmıştır.

Link bilgileri sabit bir `path1`, `path2` veya sabit topoloji listesine bağlı değildir.

---

# 22. NetworkX Topology Graph

Dinamik olarak keşfedilen switch ve link bilgileri:

```text
topology/topology_manager.py
```

tarafından yönetilmektedir.

Topoloji:

```text
NetworkX
```

graph yapısında tutulmaktadır.

Aşama 6 testinde başlangıç graph'ı:

```text
node_count = 4
edge_count = 4
```

olarak doğrulanmıştır.

---

# 23. Dinamik Shortest Path

Routing mekanizması NetworkX graph'ını kullanmaktadır.

Temel yaklaşım:

1. Güncel graph alınır.
2. Kullanılamayan veya arızalı link hesaplamadan çıkarılır.
3. Kalan graph üzerinde alternatif yollar hesaplanır.
4. Uygun shortest path seçilir.
5. Recovery mekanizmasına yol bilgisi gönderilir.

Kod içerisinde sabit:

```text
path1
path2
OVS1 -> OVS2 -> ...
```

şeklinde yol tanımları kullanılmamaktadır.

---

# 24. Aşama 5 — SDN Switch Stratejisi

Aşama 5 kapsamında aşağıdaki kararlar uygulanmış ve doğrulanmıştır:

- OVS-1, OVS-2, OVS-3 ve OVS-4 SDN omurgası olarak korunmuştur.
- Access switch'ler normal Ethernet switch olarak tutulmuştur.
- Distribution switch'ler normal Ethernet switch olarak tutulmuştur.
- SERVER tarafında normal Ethernet switch kullanılmaktadır.
- Dört OVS OS-Ken controller'a bağlanmıştır.
- OpenFlow 1.3 aktif edilmiştir.
- `fail-mode=secure` uygulanmıştır.
- Dört farklı DPID doğrulanmıştır.
- LLDP tabanlı link keşfi doğrulanmıştır.

**Aşama 5 tamamlanmıştır.**

---

# 25. Aşama 6 — Dinamik Topoloji ve Routing Doğrulaması

Aşama 6 kapsamında yeni büyük ağ üzerindeki SDN davranışı canlı olarak yeniden test edilmiştir.

## 25.1 Başlangıç Durumu

Controller:

```text
4 switch
4 link
```

keşfetmiştir.

NetworkX üzerinde:

```text
4 node
4 edge
```

graph oluşturulmuştur.

Farklı switch çiftleri için:

```text
SHORTEST_PATH
```

hesaplarının üretildiği doğrulanmıştır.

## 25.2 Kontrollü Link Failure

Test amacıyla OVS-1 ile OVS-2 arasındaki doğrudan bağlantı GNS3 üzerinden geçici olarak **Suspend** edilmiştir.

Sistem link arızasını algılamıştır.

Controller logunda:

```text
LINK_FAILURE
PORT_FAILED
RECOVERY REQUEST
FLOW_INSTALL_START
FLOW_INSTALLED
PATH_ACTIVE
```

olayları görülmüştür.

## 25.3 Alternatif Yol

Doğrudan OVS-1 ↔ OVS-2 bağlantısı kullanılamadığında sistem alternatif yolu dinamik olarak hesaplamıştır:

```text
OVS-1
  |
  v
OVS-3
  |
  v
OVS-4
  |
  v
OVS-2
```

Alternatif yol için gerekli OpenFlow recovery flow'ları switch'lere kurulmuştur.

## 25.4 Gerçek Trafik Testi

SDN omurgasını doğrulamak amacıyla kullanılan test uçları:

```text
PC1 → 10.0.0.1/24
PC2 → 10.0.0.2/24
```

OVS-1 ↔ OVS-2 linki kapalı durumdayken:

```text
PC1> ping 10.0.0.2
```

testi başarılı olmuştur.

Böylece yalnızca controller'ın alternatif yol hesapladığı değil, gerçek veri trafiğinin de alternatif yol üzerinden devam ettiği doğrulanmıştır.

Bu PC1/PC2 ağı SDN omurga doğrulama ağıdır; kurumsal VLAN kullanıcı ağlarından ayrıdır.

## 25.5 Link Recovery

Suspend edilen bağlantı tekrar **Resume** edilmiştir.

Controller tarafından:

```text
LINK_ADDED
LINK_UP
PORT_RECOVERED
```

olayları algılanmıştır.

Graph tekrar:

```text
node_count = 4
edge_count = 4
```

durumuna dönmüştür.

Port sağlık durumları yeniden:

```text
HEALTHY
```

olarak işaretlenmiştir.

Doğrudan OVS-1 ↔ OVS-2 shortest path'i yeniden kullanılabilir hale gelmiştir.

## 25.6 Son Trafik Testi

Link geri geldikten sonra:

```text
PC1> ping 10.0.0.2
```

testi tekrar başarılı olmuştur.

Sonuç olarak:

- dinamik switch keşfi,
- dinamik link keşfi,
- graph güncelleme,
- shortest-path hesaplama,
- link failure algılama,
- alternatif yol oluşturma,
- recovery flow kurulumu,
- gerçek trafik devamlılığı,
- link recovery,
- graph'ın eski durumuna dönmesi

başarıyla doğrulanmıştır.

**Aşama 6 tamamlanmıştır.**

---

# 26. Multi-Agent Mimarisi

Repository içerisinde dört temel agent bulunmaktadır.

Agent kodları baseline sistemde geliştirilmiş ve SDN controller ile ilişkili altyapıları oluşturulmuştur.

Aşama 7'nin amacı bu agent'ların yeni kurumsal ağ üzerindeki görevlerini sistematik biçimde entegre etmek ve canlı senaryolarda birlikte çalışmalarını doğrulamaktır.

---

# 27. Monitoring Agent

Dosya:

```text
agents/monitoring_agent.py
```

Başlıca görevleri:

- port durumlarını takip etmek,
- RX/TX sayaçlarını okumak,
- throughput hesaplamak,
- packet rate hesaplamak,
- drop sayaçlarını izlemek,
- error sayaçlarını izlemek,
- metrik event'leri üretmek.

Controller loglarında canlı:

```text
[MONITORING] METRIC
```

kayıtları üretilebildiği doğrulanmıştır.

---

# 28. Failure Detection Agent

Dosya:

```text
agents/failure_agent.py
```

Port ve link sağlık durumlarını:

```text
HEALTHY
DEGRADED
FAILED
```

olarak değerlendirmektedir.

Link failure durumunda:

```text
LINK_FAILURE
```

event'i oluşturabilmektedir.

Aşama 6 link kesintisi testinde failure mekanizmasının gerçek link arızasını algıladığı doğrulanmıştır.

---

# 29. Routing Agent

Dosya:

```text
agents/routing_agent.py
```

Routing Agent:

- güncel NetworkX graph'ını kullanır,
- arızalı bağlantıyı hesap dışında bırakır,
- alternatif yolları değerlendirir,
- deterministik bir alternatif yol seçer,
- Recovery Agent'a recovery isteği gönderir.

Canlı graph değiştirilmeden NetworkX görünümü üzerinden alternatif yol hesaplanmaktadır.

---

# 30. Recovery Agent

Dosya:

```text
agents/recovery_agent.py
```

Recovery Agent:

- Routing Agent'tan gelen recovery isteğini doğrular,
- uygun trafik çiftlerini belirler,
- alternatif yol boyunca OpenFlow flow'ları kurar,
- recovery flow'larını normal forwarding flow'larından ayırır,
- link geri geldiğinde recovery oturumunu yönetir.

Recovery flow'ları ayrı cookie ve priority değerleri kullanmaktadır.

Aşama 6 canlı testinde recovery flow'larının gerçek switch'lere yüklendiği doğrulanmıştır.

---

# 31. Event-Driven Agent Haberleşmesi

Agent'lar arasındaki iletişim:

```text
utils/event_bus.py
```

içerisindeki EventBus yapısı üzerinden gerçekleştirilmektedir.

Genel akış:

```text
Monitoring Agent
       |
       v
Failure Detection Agent
       |
       v
Routing Agent
       |
       v
Recovery Agent
```

Bu yaklaşım agent'ların birbirlerine doğrudan bağımlılığını azaltmakta ve sisteme yeni agent eklenmesini kolaylaştırmaktadır.

---

# 32. Self-Healing Akışı

Mevcut self-healing akışı:

```text
Link / Port Problemi
        |
        v
Monitoring Agent
        |
        v
Failure Detection Agent
        |
        v
LINK_FAILURE
        |
        v
Routing Agent
        |
        v
NetworkX Alternative Path
        |
        v
Recovery Agent
        |
        v
OpenFlow Recovery Flows
        |
        v
Traffic Continues
```

Bağlantı geri geldiğinde sistem link recovery durumunu algılar ve normal forwarding yapısına dönüş sürecini yönetebilir.

Aşama 8'de bu mekanizma kontrollü deneylerle ve ölçümlerle ayrıntılı olarak test edilecektir.

---

# 33. Startup Automation

SDN ortamını tekrar ayağa kaldırmayı kolaylaştırmak için:

```text
start_sdn.sh
```

scripti kullanılmaktadır.

Script:

- çalışan GNS3 OVS container'larını keşfeder,
- management portlarını belirler,
- management IP'lerini alır,
- controller bağlantısını ayarlar,
- OpenFlow 1.3'ü etkinleştirir,
- `fail-mode=secure` ayarını doğrular,
- OS-Ken controller'ın durumunu kontrol eder,
- controller zaten çalışıyorsa ikinci bir instance başlatmaz.

Başlatma:

```bash
cd ~/smart-sdn-gns3
./start_sdn.sh
```

Controller logu:

```bash
tail -f logs/controller.log
```

---

# 34. Dashboard

Projede Streamlit tabanlı bir dashboard bulunmaktadır.

Dosya:

```text
dashboard/app.py
```

Dashboard ile:

- controller durumu,
- switch sayısı,
- linkler,
- agent durumları,
- port metrikleri,
- failure olayları,
- routing kararları,
- recovery olayları,
- self-healing süreci

izlenebilmektedir.

Dashboard ağ kontrolüne doğrudan müdahale etmez; gözlem katmanı olarak tasarlanmıştır.

Runtime verileri:

```text
runtime/state.json
```

üzerinden okunmaktadır.

---

# 35. Testler

Repository içerisinde agent ve runtime bileşenleri için offline testler bulunmaktadır.

```text
tests/test_failure_agent_offline.py
tests/test_routing_agent_offline.py
tests/test_recovery_agent_offline.py
tests/test_runtime_state_offline.py
```

Mevcut baseline test paketi README içerisinde:

```text
41 offline test
```

olarak dokümante edilmiştir.

Buna ek olarak Aşama 5–6 kapsamında gerçek GNS3 ortamında canlı SDN doğrulamaları yapılmıştır.

---

# 36. Repository Yapısı

```text
smart-sdn-gns3/
|
├── agents/
│   ├── monitoring_agent.py
│   ├── failure_agent.py
│   ├── routing_agent.py
│   └── recovery_agent.py
│
├── controller/
│   └── sdn_controller.py
│
├── topology/
│   └── topology_manager.py
│
├── utils/
│   ├── event_bus.py
│   └── runtime_state.py
│
├── dashboard/
│   ├── app.py
│   ├── state_reader.py
│   └── requirements.txt
│
├── tests/
│   ├── test_failure_agent_offline.py
│   ├── test_routing_agent_offline.py
│   ├── test_recovery_agent_offline.py
│   └── test_runtime_state_offline.py
│
├── configs/
│   ├── router/
│   │   ├── interfaces.conf
│   │   ├── nat.nft
│   │   ├── nat.sh
│   │   ├── filter.nft
│   │   └── filter.sh
│   │
│   ├── dns/
│   │   ├── interfaces.conf
│   │   ├── dnsmasq-sdn.conf
│   │   └── dns-start.sh
│   │
│   ├── web/
│   │   ├── interfaces.conf
│   │   ├── set-dns.sh
│   │   └── web-start.sh
│   │
│   └── db/
│       ├── interfaces.conf
│       ├── mariadb-sdn.cnf
│       └── db-start.sh
│
├── gns3/
│   └── Smart_SDN_MultiAgent_v2_Work.gns3
│
├── start_sdn.sh
├── start_dashboard.sh
├── README.md
└── .gitignore
```

---

# 37. Repository Güvenliği

Runtime dosyaları, sanal ortamlar, paketler, container veri alanları ve hassas bilgiler GitHub repository'sine dahil edilmez.

`.gitignore` içerisinde diğerlerinin yanında:

```text
.env
.venv/
venv/
logs/
runtime/
*.log
*.apk
*.pcap
*.pcapng
*.vdi
*.vmdk
*.qcow2
*.iso
*.pem
*.key
*.p12
*.pfx
project-files/
snapshots/
*.gns3project
.streamlit/secrets.toml
db-data/
db-pkgs/
web-pkgs/
```

dosya ve dizinleri ignore edilmektedir.

Repository içerisinde:

- GitHub token'ları,
- API key'leri,
- gerçek veritabanı parolaları,
- private key'ler,
- runtime secret'ları

tutulmamalıdır.

---

# 38. Güncel Yol Haritası

| Aşama | Açıklama | Durum |
|---|---|---|
| **0** | Çalışan sürümü koruma | ✅ Tamamlandı |
| **1** | Mevcut topolojiyi rol bazlı düzenleme | ✅ Tamamlandı |
| **2** | Access katmanı ve yeni uç cihazlar | ✅ Tamamlandı |
| **3** | VLAN ve ağ segmentasyonu | ✅ Tamamlandı |
| **4** | Firewall, SERVER/DMZ, WEB, DNS ve DB altyapısı | ✅ Tamamlandı |
| **5** | SDN switch stratejisini netleştirme | ✅ Tamamlandı |
| **6** | Dinamik topoloji ve routing'i yeni ağda yeniden doğrulama | ✅ Tamamlandı |
| **7** | Multi-Agent mimariyi yeni kurumsal ağla tam entegre etme ve doğrulama | ➡️ **Sıradaki aşama** |
| **8** | Ölçümlü Self-Healing senaryoları | ⏳ Planlandı |
| **9** | İzleme verilerinden dataset oluşturma | ⏳ Planlandı |
| **10** | AI / Anomali Detection Agent | ⏳ Planlandı |
| **11** | Güvenlik ve politika senaryolarını genişletme | ⏳ Planlandı |
| **12** | Deneyler, dashboard ve akademik karşılaştırma | ⏳ Planlandı |

---

# 39. Aşama 0–6 Sonunda Elde Edilen Yapı

Aşama 0–6 sonunda sistem iki ana katmanı bir araya getirmektedir.

```text
                    KURUMSAL AĞ
                         |
                     ROUTER-1
                         |
       --------------------------------------
       |        |        |        |         |
     ADMIN    STAFF    GUEST   STUDENT    SERVER
      VLAN     VLAN     VLAN     VLAN       VLAN
                                             |
                              -----------------------------
                              |             |             |
                         WEB-SERVER    DNS-SERVER    DB-SERVER
```

Bunun altında SDN kontrollü omurga bulunmaktadır:

```text
                OS-Ken Controller
                       |
                 OpenFlow 1.3
                       |
          ---------------------------
          |            |            |
        OVS-1 ------ OVS-2           |
          |            |             |
        OVS-3 ------ OVS-4           |
          ---------------------------
                 SDN Backbone
```

Controller:

- switch'leri dinamik keşfetmekte,
- linkleri LLDP ile keşfetmekte,
- NetworkX graph oluşturmakta,
- shortest path hesaplamakta,
- link failure durumunda alternatif yol üretebilmekte,
- recovery flow'larını uygulayabilmektedir.

---

# 40. Sıradaki Aşama

## Aşama 7 — Multi-Agent Entegrasyonu

Agent modülleri repository içerisinde zaten bulunmaktadır.

Aşama 7'de amaç bu agent'ları sıfırdan oluşturmak değil; mevcut:

```text
Monitoring Agent
Failure Detection Agent
Routing Agent
Recovery Agent
```

bileşenlerinin yeni kurumsal GNS3 topolojisi üzerindeki görevlerini sistematik olarak doğrulamak ve birbirleriyle tam entegrasyonunu tamamlamaktır.

Bu aşamada özellikle:

- gerçek ağ metriklerinin Monitoring Agent tarafından toplanması,
- Failure Detection Agent'ın yeni ağ üzerinde olay üretmesi,
- Routing Agent'ın güncel kurumsal graph üzerinde karar vermesi,
- Recovery Agent'ın gerçek OpenFlow flow'larını uygulaması,
- agent event zincirinin doğrulanması,
- runtime state bilgilerinin güncellenmesi,
- dashboard'a doğru verilerin aktarılması

kontrol edilecektir.

---

# Sonuç

Proje başlangıçtaki küçük SDN laboratuvarından çıkarılarak gerçek bir kurum ağında karşılaşılabilecek:

- ağ segmentasyonu,
- VLAN,
- Layer-3 routing,
- NAT,
- stateful firewall,
- rol bazlı erişim kontrolü,
- DNS,
- web servisi,
- veritabanı,
- servisler arası iletişim,
- kalıcı yapılandırma,
- SDN kontrollü omurga,
- dinamik topoloji keşfi,
- graph tabanlı routing,
- link failure detection,
- alternatif yol hesaplama,
- OpenFlow tabanlı recovery

özelliklerini içeren daha kapsamlı bir yapıya dönüştürülmüştür.

Aşama 6 sonunda SDN omurgasının link arızası sırasında gerçek trafiği alternatif yoldan devam ettirebildiği ve bağlantı geri geldiğinde topolojiyi otomatik olarak güncelleyebildiği canlı GNS3 ortamında doğrulanmıştır.

Bir sonraki geliştirme adımı:

> **Aşama 7 — Multi-Agent Entegrasyonu**
