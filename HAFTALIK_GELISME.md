# Smart SDN – Haftalık Demo

## Bu Hafta Ne Yaptım?

Bu hafta GNS3 üzerinde geliştirdiğim SDN sistemini **multi-agent yapıya** dönüştürdüm ve self-healing mekanizmasını geliştirdim.

“Hocam bu hafta GNS3 üzerindeki SDN sistemini multi-agent yapıya dönüştürdüm ve link arızalarında otomatik alternatif yol hesaplayıp recovery uygulayan self-healing yapıyı çalıştırdım. Kısaca topolojiyi ve canlı dashboard’u göstereyim.”

## Multi-Agent Yapısı

Sistemde dört temel agent bulunuyor:

### 1. Monitoring Agent
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

### 2. Failure Detection Agent
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

### 3. Routing Agent
Arıza doğrulandıktan sonra alternatif yol hesaplar.

- Güncel NetworkX graph’ını kullanır.
- Arızalı linki yol hesabından çıkarır.
- Kalan topoloji üzerinde en kısa uygun yolu bulur.
- Sabit `path1` / `path2` kullanmaz.

Alternatif yol bulunursa `ALTERNATIVE_PATH` / `RECOVERY_REQUEST` üretir.

**Kısa anlatım:**  
Routing Agent arızalı bağlantıyı kullanmadan yeni yolu hesaplar.

---

### 4. Recovery Agent
Routing Agent’ın seçtiği yolu gerçek ağa uygular.

- OpenFlow flow kuralları oluşturur.
- Gerekli switchlere gönderir.
- Trafiği alternatif yola yönlendirir.
- Link geri geldiğinde failback sürecini yönetir.

Başarılı durumda `PATH_ACTIVE` görülür.

**Kısa anlatım:**  
Recovery Agent hesaplanan alternatif yolu OpenFlow üzerinden aktif hale getirir.

---

## Agentlar Nasıl Haberleşiyor?

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

## Neden Multi-Agent?

İzleme, arıza tespiti, rota hesaplama ve recovery işlemlerini ayrı sorumluluklara bölmek için multi-agent yapı kullandım.

Bu sayede sistem:
- Daha modüler
- Daha kolay geliştirilebilir
- Daha kolay test edilebilir
- İleride AI agent eklemeye daha uygun

hale geliyor.

---

## Önemli Not

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

## Kullanılan Teknolojiler

### 1. Ağ Topolojisi ve Simülasyon
- GNS3
- Open vSwitch (OVS)
- Docker
- VPCS
- Alpine Linux

### 2. SDN Controller
- OS-Ken
- Python
- OpenFlow 1.3

### 3. Dinamik Switch ve Link Keşfi
- DPID
- LLDP
- OS-Ken Topology API

### 4. Topoloji Yönetimi ve Routing
- NetworkX
- Python

### 5. Multi-Agent Mimari
- Python
- EventBus
- OpenFlow Port Statistics
- LLDP
- NetworkX
- OpenFlow 1.3

### 6. Agentlar Arası Haberleşme
- EventBus

### 7. Self-Healing ve Recovery
- OpenFlow 1.3
- OS-Ken
- NetworkX
- Recovery Agent

### 8. Monitoring ve Ağ Metrikleri
- OpenFlow PortStats
- Python

### 9. Dashboard
- Streamlit
- runtime/state.json

### 10. Başlangıç Otomasyonu
- Bash / Shell Script
- Docker CLI

### 11. Testler
- Python Offline Tests

### 12. Sürüm Kontrolü
- Git
- GitHub

---

## Dinamik Topoloji

Controller, switchleri ve switchler arasındaki bağlantıları çalışma sırasında otomatik keşfediyor.

- Switch keşfi: **OpenFlow / DPID**
- Link keşfi: **LLDP**
- Topoloji gösterimi ve yol hesabı: **NetworkX**

Kod içerisinde sabit `path1` veya `path2` tanımı bulunmuyor.  
Sistem mevcut topolojiye göre yolu dinamik olarak hesaplıyor.

---

## Self-Healing Testi

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

## Dashboard

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

## Başlangıç Otomasyonu

`start_sdn.sh` scripti ile sistem başlangıcını otomatikleştirdim.

Script GNS3 içerisindeki Open vSwitch düğümlerini buluyor, management bağlantılarını kontrol ediyor, OpenFlow 1.3 yapılandırmasını yapıyor ve switchleri OS-Ken controller'a bağlıyor.

---

## Mevcut Durum

Multi-agent self-healing altyapısı çalışıyor.

Sistem şu anda **kural tabanlı** çalışmaktadır. Henüz yapay zekâ / makine öğrenmesi modeli eklenmemiştir.

Sonraki aşamada kontrollü self-healing testleri ve performans ölçümleri yapılacaktır.
