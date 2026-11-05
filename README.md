# SMART SDN — MULTI-AGENT SELF-HEALING CAMPUS NETWORK

## Proje Gelişim Raporu ve Sunum Notları

**Son güncelleme:** 5 Kasım 2026  
**Projenin mevcut durumu:** Aşama 7 ve 7.7 tamamlandı.  
**Geliştirme ortamı:** Ubuntu 22.04, VirtualBox, GNS3, Docker, Python, OS-Ken  
**Projenin amacı:** Ağ bağlantılarında meydana gelen arızaları otomatik tespit edebilen, alternatif rota hesaplayabilen ve OpenFlow kurallarıyla kurtarma işlemini gerçekleştirebilen bir SDN sistemi geliştirmek.

---

# 1. PROJENİN AMACI

Bu projede temel amacım, bir ağdaki bağlantı arızası meydana geldiğinde sisteme manuel olarak müdahale etmek zorunda kalmadan arızanın tespit edilmesi, alternatif bir yolun hesaplanması ve iletişimin yeniden sağlanmasıdır.

Bu amaçla GNS3 üzerinde bir kampüs ağı ve dört Open vSwitch cihazından oluşan ayrı bir SDN deney omurgası oluşturdum.

Python ve OS-Ken kullanarak bir SDN Controller geliştirdim. Bu Controller içerisinde farklı görevlerden sorumlu dört agent bulunmaktadır:

- Monitoring Agent
- Failure Detection Agent
- Routing Agent
- Recovery Agent

Bu agent'lar birlikte çalışarak arıza tespiti, alternatif yol hesaplama, kurtarma ve normal duruma dönüş işlemlerini gerçekleştirir.

Sistemin durumunu canlı izleyebilmek amacıyla Streamlit kullanarak bir Dashboard ve Sunum Modu da geliştirdim.

### Projenin normal ağ simülasyonundan farkı

Projem yalnızca GNS3'te switch ve router cihazlarını birbirine bağlamaktan oluşmamaktadır.

Yazılım mühendisliği açısından geliştirdiğim temel bileşenler:

1. Python tabanlı SDN Controller.
2. Dört agent'tan oluşan modüler yapı.
3. EventBus ile olay tabanlı haberleşme.
4. LLDP ve NetworkX ile dinamik topoloji yönetimi.
5. OpenFlow ile otomatik kurtarma kurallarının uygulanması.
6. Arızadan sonra kontrollü failback mekanizması.
7. Sistemi canlı gösteren Streamlit Dashboard.

**Projenin temel katkısı:** Ağın arızaya verdiği tepkinin yazılım aracılığıyla yönetilmesi, otomatikleştirilmesi ve gözlemlenebilmesidir.

---

# 2. PROJENİN BAŞINDAN BUGÜNE GELİŞİMİ

## Aşama 1 — Çalışma ortamının hazırlanması

İlk olarak SDN sistemini geliştirebilmek için gerekli sanal ortamı hazırladım.

Kullanılan teknolojiler:

- **VirtualBox:** Ubuntu sanal makinesini çalıştırmak için.
- **Ubuntu 22.04:** GNS3, Docker, Controller ve Python kodlarının çalışması için.
- **GNS3:** Sanal ağ topolojisini oluşturmak için.
- **Docker:** Open vSwitch cihazlarını konteyner ortamında çalıştırmak için.
- **Python:** Controller ve agent yazılımlarını geliştirmek için.

Bu aşamada sanal makine ve ağ simülasyon ortamı hazırlandı.

## Aşama 2 — Kampüs ağının oluşturulması

GNS3 üzerinde gerçekçi bir kampüs ağı modeli oluşturdum.

Bu ağda:

- Access ve Distribution switch'ler
- ROUTER-1
- Yönetici, personel, öğrenci ve misafir bilgisayarları
- WEB-SERVER
- DNS-SERVER
- DB-SERVER
- NAT bağlantısı

bulunmaktadır.

Cihazların IP yapılandırmaları ve temel bağlantı testleri gerçekleştirildi.

## Aşama 3 — VLAN ve ağ servisleri

Farklı kullanıcı gruplarını birbirinden ayırmak amacıyla VLAN yapısını oluşturdum.

| VLAN | Kullanıcı grubu | Alt ağ |
|---|---|---|
| 10 | ADMIN | 10.10.10.0/24 |
| 20 | STAFF | 10.10.20.0/24 |
| 30 | GUEST | 10.10.30.0/24 |
| 40 | STUDENT | 10.10.40.0/24 |
| 50 | SERVER | 10.10.50.0/24 |

**VLAN:** Aynı fiziksel ağ üzerinde farklı mantıksal ağlar oluşturmak amacıyla kullanıldı.

**Access port:** Kullanıcı bilgisayarlarını ilgili VLAN'a bağlamak için kullanıldı.

**Trunk port:** Bir bağlantı üzerinden birden fazla VLAN'ın trafiğini taşımak için kullanıldı.

**ROUTER-1:** VLAN'lar arası iletişimi sağlamak için kullanıldı.

**NAT:** İç ağ ile dış ağ arasındaki adres dönüşümünü sağlamak için kullanıldı.

**Firewall:** Farklı kullanıcı grupları arasındaki erişimi belirli kurallarla sınırlandırmak için yapılandırıldı.

## Aşama 4 — Kampüs sunucularının kurulması

Kampüs ağında üç temel sunucu hizmeti oluşturdum.

| Sunucu | IP adresi | Kullanılan teknoloji |
|---|---|---|
| WEB-SERVER | 10.10.50.10 | lighttpd |
| DNS-SERVER | 10.10.50.53 | dnsmasq |
| DB-SERVER | 10.10.50.20 | MariaDB |

### WEB-SERVER

Kampüs ağı içerisinde web hizmeti sunmak ve ağ üzerinden erişimi test etmek için kullanıldı.

### DNS-SERVER

Alan adlarını IP adreslerine dönüştürmek için kullanıldı.

Örneğin:

- web.sdn.test
- db.sdn.test

### MariaDB

Kampüs ağındaki veritabanı hizmetini oluşturmak için kullanıldı.

`smart_sdn` adlı veritabanı ve `network_status` tablosu üzerinden sorgu işlemleri test edildi.

MariaDB'nin amacı **SDN'nin alternatif rotasını hesaplamak değil**, kampüs ağındaki gerçek bir veritabanı hizmetini temsil etmektir.

---

# 3. SDN ALTYAPISININ OLUŞTURULMASI

Kampüs ağından ayrı olarak SDN kurtarma mekanizmasını geliştirmek ve test etmek için dört Open vSwitch cihazından oluşan deney omurgası kurdum.

Cihazlar:

- OpenvSwitch-1
- OpenvSwitch-2
- OpenvSwitch-3
- OpenvSwitch-4
- PC1: 10.0.0.1
- PC2: 10.0.0.2

Switch'ler arasında hem doğrudan hem de alternatif bağlantılar bulunmaktadır.

Örnek doğrudan yol:

**OVS-1 → OVS-2**

Alternatif yol:

**OVS-1 → OVS-3 → OVS-4 → OVS-2**

Bu sayede doğrudan bağlantı kesildiğinde alternatif yol üzerinden iletişimin sağlanması test edilebilmektedir.

**Önemli:** Kampüs ağı ile dört OVS'li deney omurgası mevcut GNS3 projesinde ayrı bölümlerdir. Kampüs ağındaki tüm kullanıcı trafiğinin SDN omurgasından geçtiği uçtan uca entegrasyon henüz tamamlanmamıştır.

---

# 4. NEDEN OPEN VSWITCH KULLANDIM?

Kampüs ağında normal Ethernet switch'ler kullandım.

Ancak SDN deney omurgasında Open vSwitch tercih ettim.

Bunun temel nedeni Open vSwitch'in **OpenFlow protokolünü desteklemesidir**.

Geliştirdiğim Controller, OpenFlow aracılığıyla OVS cihazlarına özel yönlendirme kuralları gönderebilmektedir.

Böylece bağlantı arızalandığında Routing Agent'ın hesapladığı alternatif yol, Recovery Agent tarafından switch'lere uygulanabilmektedir.

### Normal switch ile yapılamaz mı?

Normal switch'ler de STP veya RSTP gibi protokollerle alternatif bağlantılar kullanabilir.

Ancak projemde kullandığım basit GNS3 Ethernet switch modeli OpenFlow Controller tarafından özel flow kurallarıyla yönetilememektedir.

Bu nedenle yazılımla kontrol edilebilir SDN deney omurgasında OVS kullandım.

### OVS daha pahalı değil mi?

Open vSwitch açık kaynaklı bir yazılımdır.

Ben OVS'leri fiziksel cihaz olarak satın almadım. GNS3 üzerinde Docker konteynerlerinde çalıştırdım.

Gerçek bir kurulumda sistem kaynakları, donanım ve bakım maliyetleri değerlendirilmelidir.

Ayrıca OVS zorunlu tek seçenek değildir; OpenFlow destekleyen başka switch'lerle de benzer bir sistem geliştirilebilir.

**Hocaya kısa cevap:**

> Kampüs ağında normal switch'ler kullandım. SDN deney bölümünde ise geliştirdiğim Controller'ın OpenFlow üzerinden dinamik yönlendirme kuralları uygulayabilmesi için Open vSwitch tercih ettim.

---

# 5. KULLANDIĞIM TEKNOLOJİLER VE GÖREVLERİ

| Teknoloji | Projede ne için kullanıldı? |
|---|---|
| VirtualBox | Ubuntu sanal makinesini çalıştırmak |
| Ubuntu | Projenin işletim sistemi ortamını sağlamak |
| GNS3 | Sanal ağ oluşturmak ve arıza testleri yapmak |
| Docker | Open vSwitch konteynerlerini çalıştırmak |
| Open vSwitch | Veri paketlerini iletmek ve OpenFlow kurallarını uygulamak |
| Python | Controller, agent'lar ve Dashboard geliştirmek |
| OS-Ken | Python ile SDN Controller geliştirmek |
| OpenFlow 1.3 | Controller ile OVS arasında kontrol mesajları ve flow kuralları iletmek |
| DPID | Switch'leri benzersiz kimlikleriyle tanımak |
| LLDP | Switch bağlantılarını otomatik keşfetmek |
| NetworkX | Ağ topolojisini grafik halinde tutmak ve rota hesaplamak |
| EventBus | Agent'lar arasında olayları iletmek |
| OpenFlow PortStats | Portların trafik, paket, hata ve düşme bilgilerini izlemek |
| JSON | Güncel sistem bilgilerini dosyada saklamak |
| Streamlit | Dashboard oluşturmak |
| Git/GitHub | Kodları ve gelişim sürecini sürüm kontrolüyle saklamak |

---

# 6. SDN CONTROLLER NASIL ÇALIŞIYOR?

Controller'ı Python ve OS-Ken kullanarak geliştirdim.

Ana dosya:

`controller/sdn_controller.py`

Controller, OpenFlow destekli switch'lerle haberleşerek ağın kontrol işlemlerini gerçekleştirir.

### Control Plane ve Data Plane

**Control Plane:** Ağın kontrol ve karar mekanizmasıdır. Projemizde SDN Controller bu tarafta yer alır.

**Data Plane:** Veri paketlerinin iletildiği taraftır. Projemizde Open vSwitch cihazları bu görevi yapar.

**Temel fark:** Controller kuralları yönetir, OVS'ler paketleri iletir.

### OpenFlow 1.3

Controller'ın Open vSwitch cihazlarına flow kuralları göndermesini sağlar.

### DPID

Her OpenFlow switch'in Controller tarafından tanınmasını sağlayan kimliktir.

### LLDP

Switch'ler arasındaki bağlantıların otomatik keşfedilmesi için kullanılır.

Örneğin Controller, OVS-1'in OVS-2 ve OVS-3 ile bağlantısını LLDP tabanlı topoloji keşfi sayesinde öğrenir.

### NetworkX

Ağdaki switch'ler ve bağlantılar bir grafik yapısıyla temsil edilir.

- Switch = Node
- Bağlantı = Edge

Bir bağlantı koptuğunda güncel topoloji değişir. Routing Agent bu grafı kullanarak alternatif rota hesaplar.

**En önemli ilişki:**

**LLDP → NetworkX → Routing Agent**

Önce bağlantılar keşfedilir, ardından ağ grafı güncellenir ve uygun yol hesaplanır.

### MAC Learning

Switch'e gelen bir paketin kaynak MAC adresine bakılarak cihazın hangi portta bulunduğu öğrenilir.

Bu bilgi normal paket iletiminde kullanılır.

### Flow

Bir switch'in belirli bir paketi nasıl ileteceğini belirleyen kuraldır.

Recovery kurallarımızda kaynak MAC, hedef MAC ve giriş portu gibi alanlar kullanılır.

---

# 7. DÖRT AGENT VE GÖREVLERİ

## Monitoring Agent

Dosya: `agents/monitoring_agent.py`

Ağdaki bağlantı ve port durumlarını izler.

İzlediği bilgiler:

- Link up/down
- Port durumu
- RX/TX trafik bilgileri
- Throughput
- Paket sayısı ve paket hızı
- Drop ve error sayaçları

Bir bağlantı koptuğunda `LINK_DOWN` olayını bildirir.

**Kısa açıklama:** Ağın gözlem katmanıdır.

## Failure Detection Agent

Dosya: `agents/failure_agent.py`

Monitoring Agent'tan gelen olayları ve port metriklerini değerlendirir.

Bağlantı arızasını `LINK_FAILURE` ile doğrular.

Port sağlık durumlarını üç şekilde sınıflandırır:

- HEALTHY: Sağlıklı
- DEGRADED: Performansı bozulmuş
- FAILED: Arızalı

**Kısa açıklama:** Ağda gerçek bir sorun olup olmadığını değerlendirir.

## Routing Agent

Dosya: `agents/routing_agent.py`

Arıza doğrulandıktan sonra NetworkX üzerindeki güncel topolojiyi kullanır.

Arızalı bağlantıyı yol hesabından çıkarır ve kullanılabilir alternatif rotayı belirler.

Örneğin:

**OVS-1 → OVS-3 → OVS-4 → OVS-2**

**Kısa açıklama:** Alternatif yolu hesaplar.

## Recovery Agent

Dosya: `agents/recovery_agent.py`

Routing Agent'ın belirlediği alternatif rota için OpenFlow kuralları oluşturur ve uygulanmasını sağlar.

Bağlantı geri geldiğinde geçici recovery kurallarının kaldırılması ve failback işlemini de yönetir.

**Kısa açıklama:** Hesaplanan alternatif yolu switch'lere uygular.

### Neden dört agent kullandım?

İzleme, arıza tespiti, rota hesaplama ve kurtarma görevlerini birbirinden ayırmak istedim.

Bu sayede sistem:

- Modüler hale geldi.
- Daha kolay test edilebilir oldu.
- Hataların hangi bileşenden kaynaklandığı daha kolay incelenebilir oldu.
- Yeni özellikler eklemeye daha uygun hale geldi.

**Önemli:** Mevcut agent'lar eğitilmiş yapay zekâ modelleri değildir. Kural ve algoritma tabanlı Python bileşenleridir. Aynı Controller sürecinde çalışırlar.

---

# 8. EVENTBUS NEDİR?

Dosya: `utils/event_bus.py`

EventBus, dört agent arasındaki olay tabanlı haberleşmeyi sağlayan yapıdır.

Örneğin:

1. Monitoring Agent bağlantının koptuğunu bildirir: `LINK_DOWN`
2. Failure Detection Agent arızayı doğrular: `LINK_FAILURE`
3. Routing Agent alternatif yolu hesaplar ve kurtarma talebi oluşturur: `RECOVERY_REQUEST`
4. Recovery Agent OpenFlow kurallarını uygular.

Bu olaylar ilgili agent'lara EventBus üzerinden iletilir.

**Neden kullandım?**

Agent'ların birbirine doğrudan bağımlı olmadan haberleşebilmesi için.

**Önemli fark:** EventBus alternatif yol hesaplamaz veya switch'lere kural göndermez. Yalnızca yazılım bileşenleri arasındaki olayları iletir.

---

# 9. SELF-HEALING, FAILOVER VE FAILBACK

### Self-Healing

Ağın arızayı algılayıp uygun kurtarma işlemleriyle iletişimi yeniden sağlayabilmesidir.

### Failover

Kullanılan bağlantı koptuğunda alternatif yola geçilmesidir.

### Failback

Arızalı bağlantı düzeldikten sonra geçici kurtarma kurallarının temizlenerek normal yönlendirme mekanizmasına dönülmesidir.

### Bizim sistemde arıza olunca ne oluyor?

1. GNS3'te OVS-1 ile OVS-2 arasındaki bağlantı Suspend edilir.
2. Controller bağlantı değişikliğini öğrenir.
3. NetworkX topolojisi güncellenir.
4. Monitoring Agent bağlantı kaybını bildirir.
5. Failure Detection Agent arızayı doğrular.
6. Routing Agent alternatif yol hesaplar.
7. Recovery Agent OpenFlow kurallarını uygular.
8. OVS cihazları uygun paketleri alternatif rota üzerinden iletir.
9. PC1–PC2 ping testiyle iletişim kontrol edilir.
10. Bağlantı Resume edildiğinde failback süreci başlar.

### Recovery kurallarının teknik özellikleri

Kurtarma kurallarımız:

- `in_port`
- `eth_src`
- `eth_dst`

alanlarıyla ilgili trafiğe uygulanır.

Recovery flow'larını normal forwarding kurallarından ayırmak için:

- **Cookie:** `0x6E`
- **Priority:** `100`

kullanılır.

Canlı testimizde iki yönlü trafik için **8 recovery flow** gözlemlendi.

Failback mekanizmasında bağlantının kararlı hale gelmesi için yaklaşık 10 saniyelik kontrol koşulu bulunmaktadır.

**Sınırlama:** Alternatif rota bulunamazsa veya kurtarma uygulanabilecek bilinen host trafiği yoksa sistem her arızayı kurtaramaz. Bu gibi durumlar kaydedilir.

---

# 10. DASHBOARD NASIL ÇALIŞIYOR?

Sistemin çalışma durumunu canlı takip edebilmek için Streamlit kullanarak Dashboard geliştirdim.

İlgili dosyalar:

- `dashboard/app.py`
- `dashboard/presentation.py`
- `dashboard/state_reader.py`
- `utils/runtime_state.py`

### runtime/state.json dosyası

Controller'ın güncel ağ durumunu kaydettiği dosyadır.

Bu dosyada:

- Switch durumları
- Aktif bağlantılar
- Arızalar
- Agent olayları
- Recovery durumu
- Trafik metrikleri

gibi bilgiler bulunur.

### Bilgi aktarımı

**Controller → runtime/state.json → Dashboard**

Controller güncel durumu dosyaya yazar.

Dashboard bu dosyayı okuyarak bilgileri ekranda gösterir.

**Önemli:** Dashboard kurtarma işlemini gerçekleştirmez. Kurtarmayı Controller ve agent'lar yapar.

### Dashboard'da gösterilen bilgiler

| Gösterge | Anlamı |
|---|---|
| Controller ONLINE | Controller çalışıyor ve veriler güncel |
| Aktif Switch | Bağlı OVS sayısı |
| Aktif Bağlantı | Keşfedilmiş aktif OVS bağlantıları |
| Aktif Arıza | Güncel arıza sayısı |
| Recovery IDLE | Aktif kurtarma oturumu yok |
| Recovery ACTIVE | Kurtarma oturumu aktif |
| FAILBACK_PENDING | Normal yönlendirmeye dönüş bekleniyor |

### Dashboard renkleri

- Mavi: Sağlıklı bağlantı
- Kırmızı kesikli: Arızalı bağlantı
- Yeşil: Aktif kurtarma rotası
- Sarı/noktalı: Kalitesi düşmüş bağlantı

### EventBus ile state.json arasındaki fark

**EventBus:** Agent'ların birbirine olay iletmesini sağlar.

**state.json:** Controller'ın güncel bilgilerini Dashboard'a aktarır.

---

# 11. YAPILAN CANLI TESTLER

GNS3 üzerinde gerçek bir bağlantı arızası oluşturarak sistemin çalışmasını test ettim.

## Test 1 — Normal ağ durumu

Dört Open vSwitch ve iki test bilgisayarı çalıştırıldı.

Dashboard'da:

- 4 aktif switch
- 4 aktif bağlantı
- 0 aktif arıza
- Recovery IDLE

görüldü.

PC1 üzerinden PC2'ye `ping 10.0.0.2` komutu çalıştırılarak iletişim doğrulandı.

## Test 2 — Bağlantı arızası

GNS3 üzerinde OVS-1 ile OVS-2 arasındaki doğrudan bağlantı Suspend edildi.

Dashboard'da:

- Aktif bağlantı: 4 → 3
- Aktif arıza: 0 → 1
- Recovery: ACTIVE

durumları gözlendi.

Routing Agent alternatif rotayı hesapladı.

Recovery Agent, ilgili OpenFlow kurallarını uyguladı.

Seçilen deneyde **8 recovery flow** görüldü.

PC1–PC2 iletişimi yeniden ping ile test edildi ve alternatif yol üzerinden başarılı sonuç alındı.

## Test 3 — Bağlantının geri getirilmesi

Aynı bağlantı Resume edildi.

Dashboard'da:

- Aktif bağlantı: 3 → 4
- Aktif arıza: 1 → 0
- FAILBACK_PENDING
- FAILBACK_COMPLETE
- Recovery IDLE

durumları gözlendi.

PC1–PC2 ping testi yeniden başarılı oldu.

**Sonuç:** Seçilen kontrollü senaryoda otomatik arıza tespiti, alternatif rota uygulaması ve failback mekanizması doğrulandı.

**Not:** Bazı bağlantı arızalarında kısa süreli paket kayıpları görülebilir. Bir testte başarılı ping alınması, her ağ koşulunda sıfır kayıp olacağını garanti etmez.

---

# 12. OTOMATİK YAZILIM TESTLERİ

GNS3'e ihtiyaç duymadan temel agent ve runtime işlemlerini doğrulamak amacıyla Python testleri geliştirdim.

| Test dosyası | Başarılı test |
|---|---:|
| test_failure_agent_offline.py | 7 |
| test_routing_agent_offline.py | 11 |
| test_recovery_agent_offline.py | 17 |
| test_runtime_state_offline.py | 6 |
| **TOPLAM** | **41 / 41** |

Test edilen temel konular:

- Arıza tespiti
- Port sağlık durumları
- Alternatif rota hesaplama
- Recovery kurallarının doğru yönetilmesi
- Failback ve kurtarma oturumları
- Runtime durum bilgilerinin oluşturulması

**Önemli:** Bu testler yazılım bileşenlerini doğrular. Bütün gerçek ağ koşullarının test edildiği veya belirli bir performans garantisi sağlandığı anlamına gelmez.

---

# 13. SUNUMDA SIRAYLA NE GÖSTERECEĞİM?

## 1. GNS3 — Kampüs ağını tanıtma

**Gösterilecek yer:** ACCESS/DIST switch'ler, ROUTER-1, kullanıcı grupları ve sunucular.

**Söyleyeceğim:**

> GNS3 üzerinde VLAN'lara ayrılmış bir kampüs ağı oluşturdum. Router, NAT ve firewall yapılandırmalarını yaptım. Ayrıca WEB, DNS ve MariaDB sunucularını ekleyerek ağ hizmetlerini test ettim.

## 2. GNS3 — SDN deney omurgasını tanıtma

**Gösterilecek yer:** OpenvSwitch-1/2/3/4 ve PC1/PC2.

**Söyleyeceğim:**

> Bu bölümde otomatik kurtarma mekanizmasını test etmek için dört Open vSwitch kullandım. Switch'leri Docker üzerinde çalıştırıyorum. Controller switch'leri DPID ile, bağlantıları LLDP ile keşfediyor. NetworkX ağ topolojisini tutuyor, OpenFlow ise switch'lere kuralları gönderiyor.

## 3. Dört agent'ı açıklama

**Gösterilecek yer:** Dashboard agent zinciri veya GitHub'daki `agents` klasörü.

**Söyleyeceğim:**

> Controller içerisinde dört agent geliştirdim. Monitoring ağı izliyor, Failure arızayı doğruluyor, Routing alternatif yolu hesaplıyor, Recovery ise OpenFlow kurallarını uyguluyor. Agent'lar EventBus üzerinden haberleşiyor.

## 4. Dashboard'ın normal durumunu gösterme

**Gösterilecek yer:** Sunum Modu.

**Söyleyeceğim:**

> Dashboard'ı Streamlit ile geliştirdim. Controller'ın state.json dosyasına yazdığı bilgileri okuyarak ağ durumunu ve agent olaylarını gösteriyor.

## 5. Ping testi

PC1 konsolunda:

`ping 10.0.0.2`

**Söyleyeceğim:**

> Öncelikle iki bilgisayarın birbirleriyle haberleşebildiğini doğruluyorum.

## 6. Bağlantı kesme ve Failover

**İşlem:** OVS-1 ile OVS-2 arasındaki doğrudan veri bağlantısına sağ tık → Suspend.

**Söyleyeceğim:**

> Şimdi doğrudan bağlantıyı kesiyorum. Sistem arızayı algılıyor, alternatif yolu hesaplıyor ve Recovery Agent OpenFlow kurallarını uyguluyor. Dashboard'da arızayı ve aktif kurtarma yolunu görüyoruz.

Ardından PC1'den PC2'ye yeniden ping gönderilir.

## 7. Bağlantıyı geri getirme ve Failback

**İşlem:** Aynı bağlantıya sağ tık → Resume.

**Söyleyeceğim:**

> Bağlantıyı yeniden aktif hale getirdim. Sistem bağlantının kararlı olduğunu kontrol ederek geçici recovery kurallarını temizliyor ve normal yönlendirmeye dönüyor. Buna Failback deniyor.

## 8. Kapanış

**Söyleyeceğim:**

> Bu projede yalnızca ağ topolojisi oluşturmadım. Python ile arızayı izleyen, doğrulayan, alternatif rota hesaplayan ve OpenFlow üzerinden kurtarma uygulayan bir kontrol sistemi geliştirdim. Sonuçları Dashboard üzerinden gösterdim. Sistemi canlı arıza senaryosu ve 41 offline test ile doğruladım.

---

# 14. HOCANIN SORABİLECEĞİ SORULAR

### 1. Bu projeyi normal ağ simülasyonundan ayıran özellik nedir?

GNS3 üzerinde yalnızca cihaz bağlantıları oluşturmadım. Python ile Controller, dört agent, dinamik rota hesaplama, OpenFlow kurtarma mekanizması ve Dashboard geliştirdim.

### 2. Neden SDN kullandın?

Ağın kontrol mekanizmasını yazılım üzerinden yönetebilmek ve bağlantı arızalarında yönlendirme kurallarını dinamik değiştirebilmek için.

### 3. Neden normal switch yerine OVS kullandın?

Kullandığım normal GNS3 switch modeli OpenFlow desteklemediği için, Controller'ın özel flow kurallarını uygulayabileceği OVS cihazlarını tercih ettim.

### 4. OVS daha pahalı değil mi?

Açık kaynak OVS'leri Docker üzerinde çalıştırıyorum. Fiziksel cihaz satın almadım. Gerçek kurulumdaki donanım ve işletme maliyetlerinin ayrıca değerlendirilmesi gerekir.

### 5. OVS zorunlu mu?

Hayır. OpenFlow destekleyen başka switch'ler de kullanılabilir.

### 6. Controller ne yapıyor?

Switch'leri OpenFlow aracılığıyla kontrol ediyor ve agent'ların yürüttüğü ağ yönetim işlemlerini koordine ediyor.

### 7. OS-Ken neden kullanıldı?

Python ile OpenFlow destekli SDN Controller geliştirmek için.

### 8. LLDP neden kullanıldı?

Switch'ler arasındaki bağlantıları otomatik keşfetmek için.

### 9. NetworkX neden kullanıldı?

Güncel topolojiyi grafik yapısında tutmak ve alternatif rota hesaplamak için.

### 10. NetworkX tek başına paketleri yeni yoldan gönderebilir mi?

Hayır. NetworkX yol hesabında kullanılır. Recovery Agent, OpenFlow kuralları ile bu yolu switch'lere uygular.

### 11. OpenFlow ne işe yarıyor?

Controller ile Open vSwitch arasında kontrol iletişimini ve flow kurallarının uygulanmasını sağlıyor.

### 12. DPID nedir?

Controller'ın her OpenFlow switch'i tanımasını sağlayan kimliktir.

### 13. Neden dört agent kullandın?

İzleme, arıza tespiti, rota hesaplama ve kurtarma görevlerini ayırarak sistemi modüler, test edilebilir ve geliştirilebilir hale getirmek için.

### 14. Agent'lar nasıl haberleşiyor?

Controller içerisindeki EventBus üzerinden olay yayınlayıp ilgili olaylara abone olarak haberleşiyorlar.

### 15. EventBus ile state.json arasındaki fark nedir?

EventBus agent'lar arasında olayları iletiyor. state.json ise Controller'ın durumunu Dashboard'a aktarıyor.

### 16. Dashboard ağı yönetiyor mu?

Hayır. Controller tarafından oluşturulan bilgileri okuyarak görselleştiriyor.

### 17. Self-Healing nedir?

Arızanın algılanması, doğrulanması, alternatif yol hesaplanması ve uygun kurtarma kurallarının uygulanması sürecidir.

### 18. Failover nedir?

Bağlantı koptuğunda alternatif yola geçilmesidir.

### 19. Failback nedir?

Bağlantı geri geldiğinde geçici recovery kurallarının kaldırılarak normal yönlendirme mekanizmasına dönülmesidir.

### 20. Neden 8 recovery flow oluştu?

Dört switch içeren alternatif rota ve iki yönlü host trafiği için özel flow kuralları oluşturulduğundan testimizde toplam sekiz recovery flow görüldü.

### 21. MariaDB ne için kullanıldı?

Kampüs ağında veritabanı hizmeti oluşturmak ve SQL sorgularıyla sunucu erişimini doğrulamak için.

### 22. MariaDB ile SDN Controller arasında doğrudan bir ilişki var mı?

MariaDB, kampüs ağının uygulama servisidir. SDN Controller'ın alternatif yol hesaplamasında kullanılmıyor.

### 23. Yapay zekâ kullandın mı?

Mevcut agent'lar kural ve algoritma tabanlıdır. Eğitilmiş bir yapay zekâ modeli henüz kullanılmıyor. İleriki aşamalarda AI tabanlı anomali tespiti geliştirilmesi planlanıyor.

### 24. Sistem her bağlantı arızasını kurtarabilir mi?

Hayır. Kurtarma için uygun alternatif yol ve gerekli trafik bilgileri bulunmalıdır.

### 25. Projenin çalıştığını nasıl kanıtladın?

GNS3 üzerinde bağlantıyı Suspend/Resume yaparak arıza ve normale dönüş süreçlerini gözlemledim. Dashboard'da recovery durumunu ve OpenFlow flow'larını kontrol ettim. PC1–PC2 ping testi ve 41 offline test ile doğrulama yaptım.

### 26. Dashboard'daki 3,0 ms neyi gösteriyor?

Örnek bir olay için Controller içindeki arıza algılama ve yolun aktif hale getirilmesi kayıtları arasındaki süreyi gösteriyor. Uçtan uca bağlantı kesintisi süresi değildir.

### 27. En önemli yazılım mühendisliği katkın nedir?

Agent'ların ayrı görevler üstlendiği, olay tabanlı haberleşen, dinamik topoloji üzerinden rota hesaplayan ve OpenFlow ile kurtarma gerçekleştiren modüler bir kontrol sistemi geliştirmek.

---

# 15. PROJENİN MEVCUT DURUMU VE SONRAKİ HEDEFLER

## Tamamlanan çalışmalar

- Ubuntu, Docker ve GNS3 ortamı
- VLAN'lı kampüs ağı
- Router, NAT ve firewall yapılandırmaları
- WEB, DNS ve MariaDB hizmetleri
- Dört Open vSwitch'li SDN deney omurgası
- OS-Ken tabanlı SDN Controller
- LLDP ile dinamik bağlantı keşfi
- NetworkX ile topoloji ve alternatif yol hesabı
- Dört agent'lı mimari
- EventBus haberleşmesi
- OpenFlow recovery kuralları
- Failover ve Failback
- Streamlit Dashboard ve Sunum Modu
- 41 başarılı offline test
- GNS3 üzerinde seçilen canlı arıza ve kurtarma testi

## Sonraki geliştirme aşamaları

| Aşama | Planlanan çalışma |
|---|---|
| 8 | Ölçümlü Self-Healing ve performans deneyleri |
| 9 | Ağ metriklerinden veri seti oluşturma |
| 10 | Yapay zekâ tabanlı anomali tespiti |
| 11 | Gelişmiş güvenlik ve politika senaryoları |
| 12 | Deneysel karşılaştırma ve akademik değerlendirme |

### Mevcut sınırlamalar

- Henüz eğitilmiş bir AI/ML modeli kullanılmıyor.
- Kampüs ağı ile OVS deney omurgası tek bir uçtan uca SDN veri yolu halinde birleştirilmiş değil.
- Farklı yük ve arıza koşullarında tekrarlı performans deneyleri henüz tamamlanmadı.
- Laboratuvar ortamındaki başarılı testler gerçek üretim ortamında kesintisiz çalışma garantisi değildir.

---

# 16. ÖNEMLİ PROJE DOSYALARI

| Dosya / klasör | Görevi |
|---|---|
| `controller/sdn_controller.py` | Ana SDN Controller |
| `topology/topology_manager.py` | NetworkX topoloji yönetimi |
| `agents/monitoring_agent.py` | Ağ izleme |
| `agents/failure_agent.py` | Arıza tespiti |
| `agents/routing_agent.py` | Alternatif rota hesabı |
| `agents/recovery_agent.py` | Kurtarma ve Failback |
| `utils/event_bus.py` | Agent haberleşmesi |
| `utils/runtime_state.py` | Dashboard için durum dosyası oluşturma |
| `dashboard/app.py` | Dashboard |
| `dashboard/presentation.py` | Sunum Modu |
| `dashboard/state_reader.py` | Durum dosyasını okuma |
| `configs/` | Router, NAT, firewall ve sunucu ayarları |
| `tests/` | Offline testler |
| `start_sdn.sh` | OVS/Controller başlatma otomasyonu |
| `start_dashboard.sh` | Dashboard başlatma |
| `README.md` | Genel proje dokümantasyonu |

---

# 17. PROJEYİ ÇALIŞTIRMA KOMUTLARI

Önce Ubuntu üzerinde GNS3 açılır ve ilgili ağ cihazları çalıştırılır.

### Controller'ı başlatma

İlk terminal:

`cd ~/smart-sdn-gns3`

`./start_sdn.sh`

Bu betik OVS yapılandırmasını yapar ve Controller'ı başlatır. Controller arka planda çalışabilir.

### Dashboard'ı başlatma

İkinci terminal:

`cd ~/smart-sdn-gns3`

`./start_dashboard.sh`

### Dashboard adresleri

**Sunum Modu:**

http://127.0.0.1:8501/?mode=sunum

**Detaylı Panel:**

http://127.0.0.1:8501/

### PC1'den PC2'ye ping

`ping 10.0.0.2`

### Controller loglarını inceleme

`tail -f logs/controller.log`

### MariaDB'yi gösterme

DB-SERVER üzerinde MariaDB oturumu açıldıktan sonra:

`SHOW DATABASES;`

`USE smart_sdn;`

`SHOW TABLES;`

`SELECT * FROM network_status LIMIT 5;`

MariaDB erişim bilgileri GitHub'da paylaşılmamalıdır.

---

# 18. SUNUM İÇİN EN KISA HATIRLATMA

**GNS3:** Ağ ortamını kurdum.

**Docker ve OVS:** Veri paketlerini ileten SDN switch'lerini çalıştırdım.

**OS-Ken:** Python tabanlı Controller geliştirdim.

**DPID:** Switch'leri tanıdım.

**LLDP:** Switch bağlantılarını keşfettim.

**NetworkX:** Ağın güncel grafını tuttum ve alternatif rota hesapladım.

**Monitoring Agent:** Ağı izledim.

**Failure Detection Agent:** Arızayı doğruladım.

**Routing Agent:** Alternatif rota hesapladım.

**Recovery Agent:** OpenFlow kurallarıyla kurtarma uyguladım.

**EventBus:** Agent'ların haberleşmesini sağladım.

**runtime/state.json:** Controller'ın durumunu kaydettim.

**Streamlit:** Dashboard ile bütün sistemi görselleştirdim.

**MariaDB:** Kampüs ağında veritabanı servisi oluşturdum.

**Test:** Link Suspend → Arıza algılama → Alternatif yol → Recovery → Ping → Link Resume → Failback.

---

## SONUÇ

Bu projede, GNS3 üzerinde oluşturduğum ağ ortamına Python ve OS-Ken tabanlı bir SDN kontrol sistemi entegre ettim.

Dört agent'ın birlikte çalışmasıyla bağlantı arızalarının algılanması, alternatif yolun hesaplanması, OpenFlow kurallarının uygulanması ve normal yönlendirmeye dönüş süreçlerini geliştirdim.

Streamlit Dashboard ile bu süreçleri izlenebilir hale getirdim.

Gerçekleştirdiğim kontrollü GNS3 deneyinde link arızası, kurtarma ve failback işlemlerini doğruladım. Yazılım bileşenlerine yönelik **41 offline test** başarıyla tamamlandı.

**Mevcut proje sürümü Aşama 7.7 seviyesindedir.** Sonraki hedeflerim ölçümlü ağ performans deneyleri, veri seti oluşturma ve yapay zekâ tabanlı anomali tespitinin geliştirilmesidir.
