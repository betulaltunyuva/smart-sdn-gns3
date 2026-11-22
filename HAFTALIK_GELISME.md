# Smart SDN – Haftalık Gelişme Kayıtları

Bu belge, Smart SDN Multi-Agent Self-Healing projesinin ilerlemesini kronolojik olarak izler. Önceden yazılmış haftalık demo notları korunmuş, Git geçmişi ve proje dosyalarıyla doğrulanabilen gelişmeler eklenmiştir.

## Kaynaklar ve tarih kuralı

| Kaynak | Ne için kullanıldı |
|:--|:--|
| `git log` (commit tarihleri) | Kod ve belge değişikliklerinin tarihi. Commit tarihi, çalışmanın yapıldığı günden sonra olabilir |
| `logs/controller.log` oturum başlıkları (`----- tarih saat start_sdn.sh -----`) | Controller'ın hangi gün/saatte başlatıldığı. Günlük satırlarının kendisi zaman damgası taşımaz |
| `deneyler/` dosya zamanları, ping kaydı başlıkları, `state.json` olay zamanları | Aşama 8 deneylerinin zamanı |

Tarihi bu kaynaklarla doğrulanamayan çalışmalar kronolojiye yerleştirilmemiş, [ayrı bir bölümde](#tarihi-doğrulanamayan-çalışmalar) listelenmiştir.

## Kronolojik özet

| Tarih (2026) | Gelişme | Kanıt |
|:--|:--|:--|
| 11 Ekim | Dinamik topoloji ve en kısa yol; Multi-Agent iskeleti (6.1); Monitoring (6.2), Failure (6.3), Routing (6.4), Recovery (6.5) checkpoint'leri | 8 commit (17:51-23:29) |
| 12 Ekim | `start_sdn.sh` otomasyonu, Streamlit dashboard, ilk README | 3 commit (21:43-22:47); ilk kayıtlı Controller oturumu 22:09 |
| 13-15 Ekim | İlk haftalık demo notları (Multi-Agent yapısı); teknoloji bölümü | 4 commit; Controller oturumları 13, 14, 15 Ekim |
| 25 Ekim | Aşama 0-4 kurumsal ağ altyapısı depoya eklendi (`configs/`, GNS3 projesi) | Commit `7cf56c3` |
| 27 Ekim | Aşama 5-6 belgelendi | Commit `a75c0d7`; Controller oturumu 15:50 |
| 30 Ekim | Aşama 7 tamamlandı; Aşama 7.7 Sunum Modu | Commit `6d63994` (`dashboard/presentation.py`); Controller oturumları 15:46 ve 18:28 |
| 2-13 Kasım | Controller oturumları; içerikleri doğrulanamadı | Yalnızca günlük başlıkları (bkz. doğrulanamayan çalışmalar) |
| 21 Kasım | Aşama 8: ön denemeler (8.1-8.4), ölçüm araçları (8.5), tekrarlı deneyler başladı | `deneyler/` dosya zamanları, ping kayıtları |
| 22 Kasım | Aşama 8: son deneyler (t3 tekrarları), sonuç raporu, README ve bu belgenin güncellenmesi | Ham veri dosya zamanları; `deneyler/ASAMA_8_SONUC_RAPORU.md` |

---

## Hafta 1 (11-12 Ekim 2026): Dinamik topoloji, ajan iskeleti ve ajanların geliştirilmesi

**11 Ekim (Git checkpoint'leri):**

- 17:51 Dinamik topoloji ve en kısa yol: LLDP ile link keşfi, NetworkX tabanlı `topology/topology_manager.py`, Controller'da DPID tabanlı switch takibi.
- 18:04 Aşama 6.1: Multi-Agent iskeleti. `utils/event_bus.py` ve dört ajan dosyası (`agents/`) oluşturuldu.
- 18:26 ve 18:43 Aşama 6.2: Monitoring Agent; periyodik OpenFlow PortDesc/PortStats isteği, port metrikleri ve yönlendirme düzeltmesi.
- 22:11 Aşama 6.3: Failure Detection Agent (`HEALTHY` / `DEGRADED` / `FAILED` sağlık durumları) ve ilk offline testler.
- 22:22 Aşama 6.4: Routing Agent karar motoru; arızalı bağlantıyı dışlayan alternatif yol hesabı ve testleri.
- 23:17 Aşama 6.5: Recovery Agent; host MAC'ine özgü OpenFlow akışları, failback ve oturum yönetimi; `tests/test_recovery_agent_offline.py`.
- 23:29 Depo güvenlik `.gitignore` kuralları.

**12 Ekim:**

- 21:43 `start_sdn.sh`: GNS3 içindeki OVS düğümlerini bulan, yönetim bağlantılarını kontrol eden ve Controller'a bağlayan başlangıç otomasyonu.
- 22:27 Streamlit dashboard (`dashboard/app.py`, `state_reader.py`) ve `utils/runtime_state.py` ile `runtime/state.json` çıktısı (Aşama 7 altyapısı); `tests/test_runtime_state_offline.py`.
- 22:47 İlk `README.md`.

## Hafta 2 (13-15 Ekim 2026): İlk haftalık demo notları

13 Ekim'de (22:54) Multi-Agent yapısı ilk kez haftalık belgeye işlenmiş; 15 Ekim'de (14:39-14:45) teknoloji bölümü ve kategoriler eklenmiştir. Bu haftanın özgün notları aşağıdadır ve değiştirilmeden korunmuştur (yalnızca başlık seviyeleri belge hiyerarşisine uyması için iki seviye indirilmiştir).

---

### Smart SDN – Haftalık Demo

#### Bu Hafta Ne Yaptım?

Bu hafta GNS3 üzerinde geliştirdiğim SDN sistemini **multi-agent yapıya** dönüştürdüm ve self-healing mekanizmasını geliştirdim.

“Hocam bu hafta GNS3 üzerindeki SDN sistemini multi-agent yapıya dönüştürdüm ve link arızalarında otomatik alternatif yol hesaplayıp recovery uygulayan self-healing yapıyı çalıştırdım. Kısaca topolojiyi ve canlı dashboard’u göstereyim.”

#### Multi-Agent Yapısı

Sistemde dört temel agent bulunuyor:

##### 1. Monitoring Agent
Ağı sürekli izler.

Takip ettiği başlıca bilgiler:
- Link up/down durumu
- Port durumu
- RX/TX trafik değerleri
- Packet rate
- Drop ve error sayaçları

Bir link koptuğunda `LINK_DOWN` olayını üretir.

**Kısa anlatım:**  
Monitoring Agent ağın gözlem katmanıdır.

---

##### 2. Failure Detection Agent
Monitoring Agent’tan gelen verileri değerlendirir.

Portları:
- `HEALTHY`
- `DEGRADED`
- `FAILED`

olarak sınıflandırır.

Link tamamen koptuğunda arızayı `LINK_FAILURE` olarak doğrular.

**Kısa anlatım:**  
Failure Detection Agent gerçekten bir arıza olup olmadığına karar verir.

---

##### 3. Routing Agent
Arıza doğrulandıktan sonra alternatif yol hesaplar.

- Güncel NetworkX graph’ını kullanır.
- Arızalı linki yol hesabından çıkarır.
- Kalan topoloji üzerinde en kısa uygun yolu bulur.
- Sabit `path1` / `path2` kullanmaz.

Alternatif yol bulunursa `ALTERNATIVE_PATH` / `RECOVERY_REQUEST` üretir.

**Kısa anlatım:**  
Routing Agent arızalı bağlantıyı kullanmadan yeni yolu hesaplar.

---

##### 4. Recovery Agent
Routing Agent’ın seçtiği yolu gerçek ağa uygular.

- OpenFlow flow kuralları oluşturur.
- Gerekli switchlere gönderir.
- Trafiği alternatif yola yönlendirir.
- Link geri geldiğinde failback sürecini yönetir.

Başarılı durumda `PATH_ACTIVE` görülür.

**Kısa anlatım:**  
Recovery Agent hesaplanan alternatif yolu OpenFlow üzerinden aktif hale getirir.

---

#### Agentlar Nasıl Haberleşiyor?

Agentlar birbirini doğrudan çağırmaz.

Aralarında `EventBus` bulunur.

Akış:

`Monitoring → Failure Detection → Routing → Recovery`

Örnek:

`LINK_DOWN`
→ `LINK_FAILURE`
→ `RECOVERY_REQUEST`
→ `PATH_ACTIVE`

EventBus kullanmamın amacı agentları birbirinden bağımsız ve modüler tutmaktır.

---

#### Neden Multi-Agent?

İzleme, arıza tespiti, rota hesaplama ve recovery işlemlerini ayrı sorumluluklara bölmek için multi-agent yapı kullandım.

Bu sayede sistem:
- Daha modüler
- Daha kolay geliştirilebilir
- Daha kolay test edilebilir
- İleride AI agent eklemeye daha uygun

hale geliyor.

---

#### Önemli Not

Mevcut agentlar yapay zekâ tabanlı değildir.

Şu anda sistem:
- Monitoring için ölçüm,
- Failure için kural tabanlı karar,
- Routing için algoritmik yol hesabı,
- Recovery için OpenFlow uygulaması

kullanmaktadır.

AI / Machine Learning sonraki aşamada eklenecektir.
Akış:

`Monitoring → Failure Detection → Routing → Recovery`

---

#### Kullanılan Teknolojiler

##### 1. Ağ Topolojisi ve Simülasyon
- GNS3
- Open vSwitch (OVS)
- Docker
- VPCS
- Alpine Linux

##### 2. SDN Controller
- OS-Ken
- Python
- OpenFlow 1.3

##### 3. Dinamik Switch ve Link Keşfi
- DPID
- LLDP
- OS-Ken Topology API

##### 4. Topoloji Yönetimi ve Routing
- NetworkX
- Python

##### 5. Multi-Agent Mimari
- Python
- EventBus
- OpenFlow Port Statistics
- LLDP
- NetworkX
- OpenFlow 1.3

##### 6. Agentlar Arası Haberleşme
- EventBus

##### 7. Self-Healing ve Recovery
- OpenFlow 1.3
- OS-Ken
- NetworkX
- Recovery Agent

##### 8. Monitoring ve Ağ Metrikleri
- OpenFlow PortStats
- Python

##### 9. Dashboard
- Streamlit
- runtime/state.json

##### 10. Başlangıç Otomasyonu
- Bash / Shell Script
- Docker CLI

##### 11. Testler
- Python Offline Tests

##### 12. Sürüm Kontrolü
- Git
- GitHub

---

#### Dinamik Topoloji

Controller, switchleri ve switchler arasındaki bağlantıları çalışma sırasında otomatik keşfediyor.

- Switch keşfi: **OpenFlow / DPID**
- Link keşfi: **LLDP**
- Topoloji gösterimi ve yol hesabı: **NetworkX**

Kod içerisinde sabit `path1` veya `path2` tanımı bulunmuyor.  
Sistem mevcut topolojiye göre yolu dinamik olarak hesaplıyor.

---

#### Self-Healing Testi

Normal durumda:

`4 Switch → 4 Aktif Link → 0 Failure`

GNS3 üzerinden bir OVS bağlantısını manuel olarak devre dışı bıraktığımda:

`Link Down`
→ `Failure Detection`
→ `Alternative Path`
→ `Recovery`

şeklinde otomatik bir süreç gerçekleşiyor.

Test sırasında:

`Aktif Link: 4 → 3`

oldu ve Routing Agent alternatif yolu hesapladı. Recovery Agent gerekli OpenFlow kurallarını uygulayarak alternatif yolu aktif hale getirdi.

---

#### Dashboard

Sistemin durumunu canlı takip etmek için **Streamlit tabanlı bir dashboard** ekledim.

Dashboard üzerinden:

- Controller durumu
- Switch ve aktif link sayısı
- Canlı ağ topolojisi
- Agent durumları
- Failure bilgileri
- Alternatif yol
- Recovery durumu
- Port ve trafik metrikleri

izlenebiliyor.

Dashboard yalnızca izleme amacıyla kullanılıyor; controller veya switchlere müdahale etmiyor.

---

#### Başlangıç Otomasyonu

`start_sdn.sh` scripti ile sistem başlangıcını otomatikleştirdim.

Script GNS3 içerisindeki Open vSwitch düğümlerini buluyor, management bağlantılarını kontrol ediyor, OpenFlow 1.3 yapılandırmasını yapıyor ve switchleri OS-Ken controller'a bağlıyor.

---

#### Mevcut Durum

Multi-agent self-healing altyapısı çalışıyor.

Sistem şu anda **kural tabanlı** çalışmaktadır. Henüz yapay zekâ / makine öğrenmesi modeli eklenmemiştir.

Sonraki aşamada kontrollü self-healing testleri ve performans ölçümleri yapılacaktır.

---

> **Güncelleme notu (22 Kasım 2026).** Yukarıdaki "Mevcut Durum" bölümündeki "sonraki aşamada kontrollü self-healing testleri ve performans ölçümleri yapılacaktır" cümlesi, belgenin yazıldığı 13-15 Ekim dönemine aittir. Bu çalışmalar Aşama 8 olarak sonradan yapılmıştır (aşağıda).

## Hafta 3-4 (16-30 Ekim 2026): Kurumsal ağ altyapısı ve Aşama 7

- **25 Ekim (commit):** Aşama 0-4 kurumsal ağ altyapısı depoya işlendi: VLAN'lı kampüs ağı için `configs/` (router, DNS, web, DB; nftables NAT ve filtre kuralları) ve `gns3/Smart_SDN_MultiAgent_v2_Work.gns3` proje dosyası. Bu commit'in kapsadığı çalışmanın gerçekte yapıldığı tarihler doğrulanamamıştır.
- **27 Ekim (commit):** Aşama 5 ve 6 README'de belgelendi. Aynı gün 15:50'de Controller oturumu kaydı vardır.
- **30 Ekim (commit):** Aşama 7 (Multi-Agent entegrasyonu, arıza-recovery-failback doğrulaması) ve **Aşama 7.7 Sunum Modu** (`dashboard/presentation.py`) tamamlandı; README yeniden yazıldı. Aynı gün 15:46 ve 18:28'de Controller oturumları kayıtlıdır. Offline test sayısı bu aşamada 41'e ulaşmıştır (7 Failure + 11 Routing + 17 Recovery + 6 Runtime).
- **Aşama 7 canlı doğrulama (README'ye göre):** GNS3'te bir omurga linki Suspend edildiğinde `LINK_DOWN → LINK_FAILURE → ALTERNATIVE_PATH → FLOW_INSTALLED → PATH_ACTIVE` zinciri izlenmiş, aktif link sayısı 4 → 3 olmuş, link Resume edildiğinde failback gözlemlenmiştir. Sunum Modu'nda tek bir olay için 3,0 ms Controller iç tepki süresi gösterilmiştir; bu değer uçtan uca kesinti değildir.

## Hafta 5-8 (31 Ekim - 20 Kasım 2026): Doğrulanabilen kayıt sınırlı

Bu dönemde depoya commit yapılmamıştır. `logs/controller.log` içinde Controller oturum başlıkları vardır (2, 5 [iki oturum], 11, 12 ve 13 Kasım); bu oturumlarda yapılan çalışmanın içeriği kayıtlardan doğrulanamamıştır.

## Hafta 9 (21-22 Kasım 2026): Aşama 8 performans ölçümü

### Aşama 8.1-8.4: Ön denemeler (21 Kasım)

Kaynak: [`deneyler/ASAMA_8_DENEY_SONUCLARI.md`](deneyler/ASAMA_8_DENEY_SONUCLARI.md). Ham ping çıktıları saklanmadığından bunlar istatistiğe dahil edilmemiştir.

| Aşama | Deney | Gözlem |
|:--|:--|:--|
| 8.1 | Normal ağ, `ping -c 20` | 20/20 yanıt, %0 kayıp, 3,089-72,380 ms. Ek 100'lük başlangıç testinde 303,7 ve 719,4 ms sıçramaları |
| 8.2 | Ping sırasında OVS-1 ↔ OVS-2 Suspend | 30 yanıttan sonra 5 ardışık timeout (31-35), ardından iletişim geri geldi; `FLOW_INSTALLED` ve `PATH_ACTIVE` günlükte görüldü. 100 paketin toplam kaybı kesinleştirilmedi |
| 8.3 | Resume ve failback | `FAILBACK_PENDING`, `FAILBACK_START`, `RECOVERY_FLOWS_REMOVED` (`removed=32/32`), `FAILBACK_COMPLETE` günlükte görüldü; sonraki 20 ping'te 0 kayıp |
| 8.4 | OpenvSwitch-3 durdurma ve yeniden başlatma, 300 ping | Controller bağlantı kayıplarını algıladı; bazı bağlantılar için `NO_ALTERNATIVE_PATH`; yeniden başlatma sonrası yönetim IP'si yeniden alındı (`192.168.122.254`), `is_connected: true`, topoloji 4 switch / 4 bağlantı. Son 20 ping'te 0 kayıp, en yüksek 407,2 ms |

### Aşama 8.5: Ölçüm altyapısı

Dosya zamanlarına göre 21 Kasım 13:43-14:21 arasında hazırlandı:

- [`deneyler/ping_analyzer.py`](deneyler/ping_analyzer.py): VPCS ping kaydı (ve isteğe bağlı pcap) analizi; kayıp, RTT (ort/medyan/P95), jitter, en uzun kayıp patlaması, Controller olay süreleri, `BASARILI` / `BASARISIZ` / `BELIRSIZ` kararı.
- [`deneyler/experiment_runner.py`](deneyler/experiment_runner.py): deney planı, şablon üretimi, state kopyalama, CSV ve SVG çıktısı.
- [`deneyler/tests/test_ping_analyzer.py`](deneyler/tests/test_ping_analyzer.py): 27 offline test (22 Kasım'da çalıştırıldı, hepsi geçti).
- Tasarım kararı: VPCS konsoluna otomatik bağlanılmadı (konsol tek istemci kabul ediyor ve bu istemci GNS3 Server); ping elle çalıştırılıp çıktı kaydedildi. Pcap yöntemi hazırlandı ancak gerçek ağda doğrulanmadı ve kullanılmadı.

### Aşama 8.5: 12 tekrarlı deney

4 senaryo x 3 tekrar, her biri `ping 10.0.0.2 -c 100`. Şablon tarihleri ve dosya zamanlarına göre:

| Deney | Şablon zamanı | Sonuç (analiz programı) |
|:--|:--|:--|
| normal_t1, t2, t3 | 21 Kasım 14:26, 14:47, 15:01 | 3 x BASARISIZ (%2, %2, **%64** kayıp) |
| otomatik_kurtarma_t1 | 21 Kasım 21:38 | BASARISIZ (%1) |
| baglanti_kopmasi_t1 | 21 Kasım 21:24 | BASARILI (%3) |
| failback_t1 | 21 Kasım 21:49 | BASARILI (%0) |
| baglanti_kopmasi_t2 | 21 Kasım 21:58 | **BASARISIZ (%70, iletişim geri gelmedi)** |
| otomatik_kurtarma_t2 | 21 Kasım 22:41 | BASARISIZ (%1) |
| failback_t2 | 21 Kasım 23:00 | BASARILI (%7) |
| baglanti_kopmasi_t3 | şablon 21 Kasım 23:09, ham veri 22 Kasım | BASARILI (%5) |
| otomatik_kurtarma_t3 | 22 Kasım 14:53 | BASARILI (%0) |
| failback_t3 | 22 Kasım 15:00 | BASARILI (%0) |

Sonuçlar [`deneyler/sonuclar/`](deneyler/sonuclar/) altında `deney_sonuclari.csv`, `senaryo_ozeti.csv` ve beş SVG grafik olarak üretilmiştir. Toplam: 6 BASARILI, 6 BASARISIZ. Ayrıntılı değerlendirme: [`deneyler/ASAMA_8_SONUC_RAPORU.md`](deneyler/ASAMA_8_SONUC_RAPORU.md).

### Aşama 8.6: Raporlama (22 Kasım)

- Aşama 8 sonuç raporu hazırlandı.
- `README.md` yeniden düzenlendi (deney sonuçları, sınırlamalar, test sonuçları).
- Bu belge kronolojik biçimde güncellendi.
- Offline testler çalıştırıldı: 41 ajan/runtime testi ve 27 analiz aracı testi geçti.

## Karşılaşılan sorunlar ve uygulanan çözüm adımları

| Sorun | Kanıt | Uygulanan adım / durum |
|:--|:--|:--|
| **LLDP link keşfi kararsızlığı:** topolojinin `edge_count=4`'ten 0'a düşmesi | Controller günlüğünde `edge_count=0` ve `edge_count=4` satırları; 9 state kopyasından üçünde `edge_count=0` ve 4 başarısız link | Controller yeniden başlatıldığında topoloji yeniden keşfedildi (22:39 ve 14:43 oturumları `edge_count=4`'e ulaştı). **Kök neden çözülmedi**; açık sorun |
| `edge_count=0` iken alternatif yol bulunamaması (`NO_ALTERNATIVE_PATH`) | `baglanti_kopmasi_t2` kopyası; iletişim geri gelmedi | Sistem sahte başarı yerine `NO_ALTERNATIVE_PATH` kaydeder; çözüm LLDP kararlılığına bağlı, açık |
| Kurtarma oturumunun yoldaki başka link düşüşüyle geçersiz kalması | `SESSION_INVALIDATED reason=recovery_path_link_down` (üç olay) | Tasarım gereği akışlar temizlenir (`removed=32/32`); davranış belgelendi |
| OVS yönetim IP'sinin kaybolması (VM durumu kaydetme / switch yeniden başlatma sonrası) | README notu; Aşama 8.4'te OpenvSwitch-3 yeniden başlatma sonrası IP yeniden alındı | Elle teşhis adımları README'ye yazıldı (`virbr0`/DHCP, `is_connected`, tek Controller, kilit dosyası) |
| VPCS konsoluna otomatik erişimin mümkün olmaması | `deneyler/README.md` bulguları (konsol GNS3 Server'a ait) | Ping elle çalıştırılıp çıktı kaydedildi; konsola müdahale edilmedi |
| Zaman damgasız ping ve geç/erken alınan state kopyaları | CSV `notlar` sütunu; `baglanti_kopmasi_t3` kopyası Suspend'den 5 sn önce alınmış | Analiz programı eşleşmeyen olayı işaretler; raporda sınırlama olarak belirtildi. Sonraki deneyler için pcap ve ping sırasında state kopyası önerildi |
| GNS3 `Operation timeout` hatası | Geliştirici gözlemi; depodaki kayıtlarda bulunmuyor | Doğrulanamadı; açık |
| Ping RTT'lerinde yüksek sıçramalar (100 ms üzeri) | 12 deneyin 10'unda | Nedeni belirlenmedi; açık |

## Tarihi doğrulanamayan çalışmalar

Aşağıdaki çalışmaların varlığı depodaki dosyalar veya belgelerle desteklenmekte, ancak ne zaman yapıldıklarına dair bağımsız bir kayıt bulunmamaktadır:

- **Aşama 0-4 (kampüs ağı):** VLAN planı, router-on-a-stick, nftables NAT/firewall, WEB/DNS/DB sunucuları ve GNS3 projesinin kurulumu. Yalnızca 25 Ekim commit'i vardır; asıl çalışma tarihleri doğrulanamamıştır.
- **Aşama 5 (OpenFlow 1.3 switch mimarisi):** 27 Ekim README commit'inden önce tamamlandığı anlaşılmaktadır; tarih doğrulanamamıştır.
- **WEB → DNS → DB servis zinciri ve MariaDB sorgu doğrulaması:** önceki README sürümünde belirtilmişti; bu oturumda yeniden doğrulanmadı.
- **2-13 Kasım Controller oturumları:** yalnızca günlük başlıkları vardır.
- **22 Kasım 15:04-15:33 ek denemeler:** `runtime/state.json` içinde `PATH_ACTIVE`, `FAILBACK_START` ve `FAILBACK_COMPLETE` adımları olan incident'lar bulunur; bunların hangi amaçla yapıldığı kayıtlı değildir ve 12 deneyin parçası değildir.
- **`datasets/` klasörü:** boş; 10 Ekim 2026 tarihli dosya zamanı vardır, içeriği yoktur.

## Projenin mevcut durumu (22 Kasım 2026)

**Tamamlananlar:** Aşama 0-7.7 (kampüs ağı, SDN omurgası, dinamik topoloji, dört ajan, EventBus, self-healing, failback, dashboard ve Sunum Modu); Aşama 8 ölçüm altyapısı ve 12 deneyin tamamı; Aşama 8 sonuç raporu; 68 offline test (41 + 27) geçiyor.

**Aşama 8'in dürüst özeti:**

- Mekanizma çalışıyor: dört ayrı olayda `DETECTED → PATH_ACTIVE` süresi 7,5-18,5 ms (Controller iç süresi; uçtan uca kesinti değildir).
- Kullanıcı tarafında başarılı bağlantı kopması denemelerinde 2 ve 5 paketlik kesinti gözlendi.
- 12 deneyin 6'sı `BASARISIZ`; normal ağda %64 ve bağlantı kopmasında %70 kayıp yaşandı; topoloji kararsızlığı (LLDP) açık sorundur.
- Otomatik kurtarma ve failback senaryolarında düşük kaybın Recovery Agent'a atfı bu veriyle kanıtlanamadı; 12 deneyin state kopyalarında `FAILBACK_COMPLETE` kayıtlı değildir.

**Kalan geliştirmeler:**

1. LLDP topoloji kararsızlığının kök neden analizi.
2. Pcap ile zaman damgalı ölçüm; ping sırasında OVS akış tablosu ve state kaydı; Suspend/Resume anının kaydı.
3. En az 10 tekrar, kontrollü başlangıç durumu, Recovery Agent'sız taban çizgisi ve istatistiksel karşılaştırma.
4. Anahtar arızası, farklı bağlantılar ve TCP/UDP yükü senaryoları.
5. Aşama 9-12: veri seti üretimi, AI/anomali tespit ajanı, gelişmiş güvenlik ve politika senaryoları, deneysel karşılaştırma.
