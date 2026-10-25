# Multi-Agent Tabanlı Akıllı Self-Healing SDN

## Proje Hakkında

Bu proje, **GNS3 üzerinde gerçekçi bir kurumsal ağ topolojisi kurarak Software-Defined Networking (SDN), Multi-Agent sistemler, ağ izleme, otomatik hata tespiti, alternatif yol hesaplama ve self-healing mekanizmalarını bir araya getirmeyi** amaçlamaktadır.

Projenin temel teknolojileri:

- **GNS3**
- **Open vSwitch (OVS)**
- **OpenFlow 1.3**
- **OS-Ken Controller**
- **Python**
- **NetworkX**
- **Multi-Agent mimari**
- **nftables**
- **VLAN**
- **Docker tabanlı GNS3 düğümleri**
- **dnsmasq**
- **lighttpd**
- **MariaDB**
- **Streamlit Dashboard**

Proje ilk olarak daha küçük bir SDN laboratuvar topolojisi üzerinde geliştirilmiş; dinamik topoloji keşfi, routing, Monitoring Agent, Failure Detection Agent, Routing Agent ve Recovery Agent bileşenleri oluşturulmuştur.

Daha sonra proje, daha gerçekçi bir kurumsal ağ senaryosuna taşınmak üzere **`Smart_SDN_MultiAgent_v2_Work`** topolojisi ile genişletilmiştir.

---

# Güncel Durum

> **25 Ekim 2026 itibarıyla güncel `Smart_SDN_MultiAgent_v2_Work` geliştirme planında Aşama 0–4 tamamlanmıştır.**
>
> **Sıradaki aşama: Aşama 5 — SDN Switch Stratejisinin Netleştirilmesi**

Şu ana kadar tamamlanan ana çalışmalar:

- Çalışan eski SDN sürümünün korunması
- Yeni ve daha büyük GNS3 topolojisinin hazırlanması
- Kullanıcı gruplarının ayrılması
- Access ve Distribution katmanlarının oluşturulması
- VLAN mimarisinin kurulması
- Router-on-a-Stick yapılandırması
- VLAN'lar arası routing
- NAT ve internet erişimi
- Stateful firewall
- Rol bazlı ağ erişim politikaları
- WEB-SERVER
- DNS-SERVER
- DB-SERVER
- Yerel DNS kayıtları
- WEB → DB gerçek servis bağlantısı
- Ağ ve servis yapılandırmalarının kalıcı hale getirilmesi
- Stop/Start sonrası kalıcılık testleri

---

# 1. Güncel Ağ Mimarisi

Yeni topoloji, küçük laboratuvar ağından daha gerçekçi bir **kurumsal ağ modeline** dönüştürülmüştür.

Kullanıcılar farklı ağ segmentlerine ayrılmıştır.

| VLAN | Rol | Ağ |
|---|---|---|
| VLAN 10 | ADMIN | `10.10.10.0/24` |
| VLAN 20 | STAFF | `10.10.20.0/24` |
| VLAN 30 | GUEST | `10.10.30.0/24` |
| VLAN 40 | STUDENT | `10.10.40.0/24` |
| VLAN 50 | SERVER | `10.10.50.0/24` |

Her VLAN için ROUTER-1 üzerinde bir gateway bulunmaktadır:

```text
VLAN 10 → 10.10.10.1
VLAN 20 → 10.10.20.1
VLAN 30 → 10.10.30.1
VLAN 40 → 10.10.40.1
VLAN 50 → 10.10.50.1
```

---

# 2. Kullanıcı Grupları

Topolojide farklı kullanıcı rollerini temsil eden uç cihazlar bulunmaktadır.

## ADMIN

```text
ADMIN-PC1
ADMIN-PC2
```

ADMIN cihazları VLAN 10 içerisindedir.

ADMIN ağı, yönetim amaçlı en geniş erişim yetkisine sahip kullanıcı grubudur.

---

## STAFF

```text
STAFF-PC1
STAFF-PC2
```

STAFF cihazları VLAN 20 içerisindedir.

Personel ağı, diğer kullanıcı VLAN'larından izole edilmiştir ancak sunucu ağına ve internete erişebilir.

---

## GUEST

```text
GUEST-PC1
GUEST-PC2
```

GUEST cihazları VLAN 30 içerisindedir.

Misafir kullanıcıların:

- internete çıkmasına izin verilir,
- DNS hizmetini kullanmasına izin verilir,
- kurumun diğer kullanıcı ağlarına erişmesine izin verilmez.

---

## STUDENT

```text
STUDENT-PC1
STUDENT-PC2
```

STUDENT cihazları VLAN 40 içerisindedir.

Öğrenci ağı:

- sunucu hizmetlerini kullanabilir,
- internete çıkabilir,
- ADMIN, STAFF ve GUEST ağlarından izole edilmiştir.

---

# 3. Access ve Distribution Katmanı

Yeni topolojide kullanıcı cihazları doğrudan SDN omurgasına bağlanmak yerine access switch'ler üzerinden bağlanmaktadır.

Kullanılan access switch'ler:

```text
ACCESS-SW1
ACCESS-SW2
ACCESS-SW3
ACCESS-SW4
```

Distribution katmanında:

```text
DIST-SW1
DIST-SW2
```

bulunmaktadır.

Bu yapı ile topoloji daha gerçekçi bir kampüs/kurum ağına dönüştürülmüştür.

---

# 4. VLAN ve Ağ Segmentasyonu

VLAN'lar ile kullanıcı grupları mantıksal olarak birbirinden ayrılmıştır.

ROUTER-1 üzerinde VLAN alt arayüzleri kullanılarak **Router-on-a-Stick** yapısı oluşturulmuştur.

Örnek alt arayüzler:

```text
eth0.10
eth0.20
eth0.30
eth0.40
eth0.50
```

Bu arayüzler sayesinde farklı VLAN'lar arasında routing yapılabilmektedir.

VLAN yapılandırmalarının cihaz yeniden başlatıldığında kaybolmaması için gerekli ağ ayarları kalıcı hale getirilmiştir.

---

# 5. ROUTER-1

ROUTER-1 ağın merkezi Layer-3 bileşenidir.

Görevleri:

- VLAN gateway'lerini sağlamak
- VLAN'lar arasında routing yapmak
- internet erişimini yönetmek
- NAT uygulamak
- firewall politikalarını uygulamak

Ayrıca dış ağ bağlantısı için ayrı bir arayüz kullanılmaktadır.

---

# 6. NAT ve İnternet Erişimi

İç ağların internete çıkabilmesi için ROUTER-1 üzerinde **nftables tabanlı NAT** yapılandırılmıştır.

NAT kapsamına şu ağlar dahildir:

```text
10.10.10.0/24
10.10.20.0/24
10.10.30.0/24
10.10.40.0/24
10.10.50.0/24
```

İç ağlardan gelen trafik dış arayüz üzerinden masquerade edilmektedir.

NAT yapılandırması:

```text
configs/router/nat.nft
configs/router/nat.sh
```

dosyalarıyla dokümante edilmiştir.

NAT yapılandırmasının Stop → Start sonrasında tekrar aktif olduğu doğrulanmıştır.

---

# 7. Stateful Firewall

ROUTER-1 üzerinde **nftables tabanlı stateful firewall** oluşturulmuştur.

Stateful yapı sayesinde mevcut bağlantılara ait dönüş paketleri:

```text
ct state established,related accept
```

mantığı ile kabul edilmektedir.

Böylece yalnızca tek yönlü IP filtreleme yerine bağlantı durumunu takip eden daha gerçekçi bir firewall yapısı oluşturulmuştur.

Firewall yapılandırmaları:

```text
configs/router/filter.nft
configs/router/filter.sh
```

altında tutulmaktadır.

---

# 8. Rol Bazlı Erişim Politikaları

Firewall ile kullanıcı grupları arasında rol bazlı erişim kontrolü uygulanmaktadır.

Genel politika:

### ADMIN

ADMIN ağı yönetim ağıdır ve diğer gerekli ağlara erişebilir.

### STAFF

STAFF:

```text
SERVER → erişebilir
Internet → erişebilir
```

ancak diğer kullanıcı VLAN'larına doğrudan erişemez.

### STUDENT

STUDENT:

```text
SERVER → erişebilir
Internet → erişebilir
```

ancak ADMIN, STAFF ve GUEST VLAN'larından izole edilmiştir.

### GUEST

GUEST:

```text
Internet → erişebilir
DNS → erişebilir
```

ancak kurumun diğer iç VLAN'larına erişemez.

Firewall testleri gerçek VPCS cihazları üzerinden ping testleriyle doğrulanmıştır.

---

# 9. SERVER VLAN

Sunucular için ayrı bir:

```text
VLAN 50
10.10.50.0/24
```

sunucu ağı oluşturulmuştur.

Bu ağda üç temel servis bulunmaktadır:

```text
WEB-SERVER
DNS-SERVER
DB-SERVER
```

---

# 10. WEB-SERVER

WEB-SERVER adresi:

```text
10.10.50.10
```

Sunucuda:

```text
lighttpd
```

kullanılmaktadır.

Test amacıyla hazırlanan web sayfası:

```text
Smart SDN Network
WEB-SERVER is running successfully.
IP: 10.10.50.10
```

şeklinde yanıt vermektedir.

WEB-SERVER'ın hem localhost üzerinden hem de ağ üzerinden erişilebilir olduğu doğrulanmıştır.

DNS kaydı:

```text
web.sdn.test → 10.10.50.10
```

şeklindedir.

WEB-SERVER için kullanılan kalıcı yapılandırmalar:

```text
configs/web/
```

altında tutulmaktadır.

---

# 11. DNS-SERVER

DNS-SERVER adresi:

```text
10.10.50.53
```

DNS hizmeti için:

```text
dnsmasq
```

kullanılmaktadır.

Yerel DNS kayıtları:

```text
web.sdn.test → 10.10.50.10
db.sdn.test  → 10.10.50.20
```

olarak yapılandırılmıştır.

Aynı DNS sunucusunun internet alan adlarını da çözebildiği doğrulanmıştır.

Örneğin:

```text
google.com
```

gibi dış alan adları çözümlenebilmektedir.

DNS yapılandırmaları:

```text
configs/dns/
```

altında saklanmaktadır.

---

# 12. DB-SERVER

DB-SERVER adresi:

```text
10.10.50.20
```

Veritabanı yönetim sistemi:

```text
MariaDB 11.8.9
```

olarak kurulmuştur.

Projeye ait veritabanı:

```text
smart_sdn
```

olarak oluşturulmuştur.

Test tablosu:

```text
network_status
```

Tabloda örnek olarak:

```text
DB-SERVER | ACTIVE
```

kaydı bulunmaktadır.

---

# 13. WEB-SERVER → DB-SERVER Bağlantısı

WEB-SERVER'ın DB-SERVER'a gerçek MariaDB bağlantısı kurabildiği doğrulanmıştır.

Bağlantı:

```text
WEB-SERVER
    ↓
db.sdn.test
    ↓
DNS-SERVER
    ↓
10.10.50.20
    ↓
TCP / 3306
    ↓
MariaDB
    ↓
smart_sdn
```

şeklinde çalışmaktadır.

WEB-SERVER üzerinden:

```sql
SELECT * FROM network_status;
```

sorgusu çalıştırılmış ve:

```text
DB-SERVER | ACTIVE
```

sonucu alınmıştır.

Bu test sayesinde:

- DNS çözümleme
- WEB → DB iletişimi
- TCP/3306 erişimi
- MariaDB kullanıcı yetkisi
- veritabanı
- tablo
- veri

tek bir uçtan uca test ile doğrulanmıştır.

> Veritabanı parolaları ve diğer hassas bilgiler GitHub deposunda tutulmamaktadır.

---

# 14. Kalıcılık

GNS3 Docker düğümlerinde bazı paket ve runtime değişikliklerinin yeniden başlatma sonrasında kaybolabilmesi nedeniyle servisler için ayrıca kalıcılık mekanizmaları hazırlanmıştır.

Kalıcı hale getirilen başlıca bileşenler:

- Router IP yapılandırmaları
- VLAN gateway'leri
- NAT
- Firewall
- DNS
- WEB-SERVER
- DB-SERVER IP adresi
- MariaDB paketleri
- MariaDB veri dizini
- MariaDB başlangıç scripti
- WEB başlangıç scripti
- DNS başlangıç scripti

DB-SERVER için veritabanı dosyaları kalıcı bir veri dizininde tutulmaktadır.

Stop → Start sonrasında:

```text
10.10.50.20
MariaDB servisi
smart_sdn veritabanı
network_status tablosu
DB-SERVER | ACTIVE kaydı
```

korunmuştur.

Bu nedenle DB-SERVER kalıcılık testi başarıyla tamamlanmıştır.

---

# 15. Önceki / Baseline SDN Çekirdeği

Yeni kurumsal topolojiden önce proje daha küçük bir SDN laboratuvar ağı üzerinde geliştirilmiştir.

Baseline topoloji:

```text
PC1
 |
OVS1 ----- OVS2
 |           |
OVS3 ----- OVS4
             |
            PC2
```

Bu topoloji üzerinde geliştirilen özellikler yeni topolojinin SDN katmanında tekrar kullanılacaktır.

---

# 16. OS-Ken ve OpenFlow

Controller:

```text
controller/sdn_controller.py
```

dosyasında bulunmaktadır.

Kullanılan protokol:

```text
OpenFlow 1.3
```

Controller bağlantısı:

```text
tcp:192.168.122.1:6653
```

şeklinde kullanılmaktadır.

OVS tarafında:

```text
br0
OpenFlow13
fail-mode=secure
```

yapısı kullanılmaktadır.

---

# 17. Dinamik Topoloji Keşfi

Controller'ın switch ve bağlantıları sabit olarak tanımlaması yerine çalışma anında keşfetmesi amaçlanmıştır.

### Switch keşfi

Switch'ler DPID üzerinden otomatik olarak keşfedilmektedir.

### Link keşfi

OS-Ken'in:

```text
--observe-links
```

özelliği kullanılarak LLDP tabanlı link keşfi yapılmaktadır.

### Graph

Keşfedilen topoloji:

```text
NetworkX
```

graph yapısında tutulmaktadır.

Bu işlemler:

```text
topology/topology_manager.py
```

üzerinden yönetilmektedir.

---

# 18. Dinamik Routing

Routing Agent, NetworkX graph'ı üzerinden alternatif yollar hesaplayabilmektedir.

Temel yaklaşım:

1. Arızalı bağlantıyı graph hesaplamasından çıkar.
2. Kalan topoloji üzerinde alternatif yol ara.
3. En uygun yolu belirle.
4. Recovery Agent'a gönder.

Kod içinde sabit:

```text
path1
path2
OVS1 → OVS2 → ...
```

gibi yol tanımları kullanılmamaktadır.

---

# 19. Multi-Agent Mimarisi

Projede dört temel agent bulunmaktadır.

## Monitoring Agent

Dosya:

```text
agents/monitoring_agent.py
```

Görevleri:

- Port durumlarını takip etmek
- RX/TX trafiğini izlemek
- throughput hesaplamak
- packet rate hesaplamak
- drop/error sayaçlarını takip etmek

---

## Failure Detection Agent

Dosya:

```text
agents/failure_agent.py
```

Port ve link durumlarını:

```text
HEALTHY
DEGRADED
FAILED
```

olarak değerlendirebilir.

---

## Routing Agent

Dosya:

```text
agents/routing_agent.py
```

Görevi:

- arızalı bağlantıyı belirlemek,
- NetworkX graph'ını kullanmak,
- alternatif yol bulmak,
- Recovery Agent'a recovery isteği göndermektir.

---

## Recovery Agent

Dosya:

```text
agents/recovery_agent.py
```

Görevleri:

- recovery isteğini doğrulamak,
- alternatif yol için OpenFlow kuralları hazırlamak,
- recovery flow'larını switch'lere göndermek,
- bağlantı geri geldiğinde failback gerçekleştirmek.

Recovery flow'ları normal forwarding flow'larından farklı cookie ve priority değerleriyle ayrılmaktadır.

---

# 20. Event-Driven Agent Haberleşmesi

Agent'lar birbirlerini doğrudan çağırmak yerine:

```text
utils/event_bus.py
```

içerisindeki EventBus üzerinden haberleşmektedir.

Basitleştirilmiş akış:

```text
Monitoring
    ↓
Failure Detection
    ↓
Routing
    ↓
Recovery
```

Bu yapı modülerliği artırmakta ve ileride yeni agent'ların sisteme eklenmesini kolaylaştırmaktadır.

---

# 21. Self-Healing Akışı

Mevcut baseline SDN çekirdeğinde self-healing mantığı:

```text
Link arızası
    ↓
Monitoring Agent
    ↓
Failure Detection Agent
    ↓
LINK_FAILURE
    ↓
Routing Agent
    ↓
Alternatif yol
    ↓
Recovery Agent
    ↓
OpenFlow recovery flow'ları
```

Link geri geldiğinde sistem:

```text
FAILBACK_PENDING
```

durumuna geçebilir ve kararlılık süresi sonrasında recovery flow'larını kaldırarak normal forwarding yapısına dönebilir.

---

# 22. Dashboard

Projenin mevcut baseline SDN çekirdeği için Streamlit tabanlı bir dashboard geliştirilmiştir.

Dosya:

```text
dashboard/app.py
```

Dashboard üzerinden:

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

Dashboard sisteme müdahale etmez; salt okunur bir gözlem katmanıdır.

Runtime verileri:

```text
runtime/state.json
```

üzerinden okunmaktadır.

---

# 23. Startup Automation

Baseline SDN ortamında OVS ve controller başlangıç işlemlerini kolaylaştırmak amacıyla:

```text
start_sdn.sh
```

geliştirilmiştir.

Script:

- çalışan GNS3 Open vSwitch container'larını keşfeder,
- management portlarını belirler,
- DHCP ile management IP'si alır,
- controller bağlantısını ayarlar,
- OpenFlow 1.3 yapılandırmasını kontrol eder,
- controller'ı başlatabilir.

---

# 24. Testler

Multi-Agent ve routing bileşenleri için offline testler bulunmaktadır.

```text
tests/test_failure_agent_offline.py
tests/test_routing_agent_offline.py
tests/test_recovery_agent_offline.py
tests/test_runtime_state_offline.py
```

Baseline SDN çekirdeğinde toplam:

```text
41 offline test
```

başarıyla çalıştırılmıştır.

> Bu testler mevcut agent kodunun davranışlarını doğrulamaktadır. Yeni `v2_Work` kurumsal topolojisi üzerindeki canlı SDN entegrasyonu Aşama 5 ve sonrasında yeniden doğrulanacaktır.

---

# 25. Repository Yapısı

```text
smart-sdn-gns3/
│
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

Runtime, Docker veri alanı, veritabanı binary dosyaları, paketler ve hassas bilgiler GitHub deposuna dahil edilmez.

---

# 26. Güvenlik ve Repository Politikası

Aşağıdaki dosyalar GitHub'a gönderilmez:

```text
.env
.venv/
logs/
runtime/
*.log
*.apk
db-data/
db-pkgs/
web-pkgs/
project-files/
snapshots/
*.gns3project
.streamlit/secrets.toml
```

Ayrıca:

- veritabanı parolaları,
- API key'leri,
- token'lar,
- özel anahtarlar,
- container runtime verileri

repository içerisinde tutulmaz.

---

# 27. Güncel Yol Haritası

| Aşama | Açıklama | Durum |
|---|---|---|
| **0** | Çalışan sürümü koruma | ✅ Tamamlandı |
| **1** | Mevcut topolojiyi rol bazlı düzenleme | ✅ Tamamlandı |
| **2** | Access katmanı ve yeni uç cihazlar | ✅ Tamamlandı |
| **3** | VLAN ve ağ segmentasyonu | ✅ Tamamlandı |
| **4** | Firewall, SERVER/DMZ, WEB, DNS ve DB altyapısı | ✅ Tamamlandı |
| **5** | SDN switch stratejisini netleştirme | ➡️ **Sıradaki aşama** |
| **6** | Dinamik topoloji ve routing'i yeni ağda yeniden doğrulama | ⏳ Planlandı |
| **7** | Multi-Agent mimariyi yeni ağla entegre etme | ⏳ Planlandı |
| **8** | Self-Healing ve ölçümlü failure/recovery testleri | ⏳ Planlandı |
| **9** | İzleme verilerinden dataset oluşturma | ⏳ Planlandı |
| **10** | AI / Anomali Detection Agent | ⏳ Planlandı |
| **11** | Güvenlik saldırı ve politika senaryolarını genişletme | ⏳ Planlandı |
| **12** | Dashboard, deneyler ve akademik karşılaştırma | ⏳ Planlandı |

---

# 28. Aşama 0–4 Sonunda Elde Edilen Yapı

Şu anda çalışan altyapı özetle:

```text
                         INTERNET
                            |
                         ROUTER-1
                            |
          -------------------------------------
          |        |        |        |        |
       VLAN10   VLAN20   VLAN30   VLAN40   VLAN50
       ADMIN    STAFF    GUEST    STUDENT   SERVER
                                             |
                              -----------------------------
                              |             |             |
                         WEB-SERVER    DNS-SERVER    DB-SERVER
                         10.10.50.10   10.10.50.53   10.10.50.20
                              |                           |
                              -------- MariaDB -----------
```

Bunun altında SDN omurgası ve Open vSwitch altyapısı bulunmaktadır.

Aşama 5'te amaç, mevcut OVS cihazlarının yeni mimarideki rollerini kesinleştirmek ve hangi bağlantıların gerçekten **SDN/OpenFlow kontrolüne** bırakılacağını belirlemektir.

---

# Sonuç

Projenin ilk bölümünde yalnızca bir SDN laboratuvar topolojisi oluşturmak yerine, gerçek bir ağda karşılaşılabilecek:

- kullanıcı segmentasyonu,
- VLAN,
- routing,
- NAT,
- firewall,
- DNS,
- web servisi,
- veritabanı,
- servisler arası iletişim,
- kalıcı yapılandırma

gibi bileşenler de sisteme eklenmiştir.

Böylece sonraki aşamalardaki **SDN, Multi-Agent, Self-Healing ve AI çalışmalarının test edilebileceği daha gerçekçi bir altyapı** hazırlanmıştır.

Bir sonraki geliştirme adımı:

> **Aşama 5 — SDN Switch Stratejisinin Netleştirilmesi**
