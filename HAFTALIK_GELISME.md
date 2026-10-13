# Smart SDN – Haftalık Demo

## Bu Hafta Ne Yaptım?

Bu hafta GNS3 üzerinde geliştirdiğim SDN sistemini **multi-agent yapıya** dönüştürdüm ve self-healing mekanizmasını geliştirdim.

Sistemde dört agent bulunuyor:

- **Monitoring Agent:** Ağdaki linkleri ve port durumlarını izliyor.
- **Failure Detection Agent:** Link veya port arızalarını tespit ediyor.
- **Routing Agent:** NetworkX üzerinden alternatif yolu hesaplıyor.
- **Recovery Agent:** Hesaplanan alternatif yolu OpenFlow kurallarıyla devreye alıyor.

Akış:

`Monitoring → Failure Detection → Routing → Recovery`

---

## Kullandığım Teknolojiler

- **GNS3:** Sanal ağ topolojisini oluşturmak ve link arızalarını test etmek için
- **Open vSwitch (OVS):** Yazılımsal switch olarak
- **OS-Ken Controller:** SDN controller olarak
- **OpenFlow 1.3:** Controller ile Open vSwitch arasındaki haberleşme için
- **Python:** Controller, agent ve yardımcı modüllerin geliştirilmesi için
- **NetworkX:** Ağ topolojisini graph olarak tutmak ve alternatif yol hesaplamak için
- **LLDP:** Switchler arasındaki linkleri dinamik olarak keşfetmek için
- **Docker:** GNS3 içerisindeki Open vSwitch düğümlerini container olarak çalıştırmak için
- **Streamlit:** Canlı izleme dashboard'unu oluşturmak için
- **EventBus:** Agent'ların olay tabanlı haberleşmesi için
- **Bash / Shell Script:** Sistem başlangıcını otomatikleştirmek için
- **Git / GitHub:** Sürüm kontrolü ve proje takibi için

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
