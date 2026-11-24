# Aşama 9 - SDN Veri Toplama ve Etiketleme Raporu

## 1. Amaç
Akıllı SDN kampüs ağında dört farklı ağ durumuna ait
gerçek ölçümler toplanmış ve etiketlenmiştir.

## 2. Kullanılan Altyapı
- GNS3 ve 4 Open vSwitch
- OpenFlow 1.3
- OS-Ken Controller
- Monitoring, Failure Detection, Routing ve Recovery ajanları
- CSV tabanlı veri toplama ve etiketleme

## 3. Veri Seti

| Senaryo | Kayıt |
|---|---:|
| NORMAL | 4189 |
| LOAD | 590 |
| CONGESTION | 1299 |
| FAILURE | 295 |
| TOPLAM | 6373 |

Birleştirilmiş dosya:
`datasets/stage9_birlesik_etiketli.csv`

## 4. Deney Sonuçları

### NORMAL
- Kontrollü arıza veya yoğun yük uygulanmadı.
- İzlenen 8 bağlantı portunda durum UP.
- 300 pingden 298 yanıt alındı.
- Paket kaybı: %0,67.
- Ortalama RTT: 37,065 ms.
- Medyan RTT: 7,353 ms.
- P95 RTT: 110,756 ms.
- Maksimum RTT: 3286,714 ms.
- Yüksek gecikmelerin nedeni kesinleştirilmedi.

### LOAD
- Kontrollü trafik yükü oluşturuldu.
- 590 port ölçümü LOAD olarak etiketlendi.
- Bu deneyde doğrulanan maksimum throughput:
  yaklaşık 0,338 Mbps.

### CONGESTION
- OVS bağlantısına 2 Mbps TBF sınırı uygulandı.
- Yük sırasında 300 pingden 3 paket kayboldu.
- Ping paket kaybı: %1.
- tc kuyruğunda 199 dropped paketi gözlendi.
- 1299 kayıt CONGESTION olarak etiketlendi.
- Deney sonunda hız sınırı kaldırıldı.

### FAILURE
- OVS-1 ile OVS-2 arasındaki doğrudan link
  yaklaşık 25 saniye kapatıldı.
- Port ölçümlerinde link_up=0 ve admin_up=0 görüldü.
- Recovery loglarında alternatif yol kurma ve
  failback olayları gözlendi.
- Ping sırasında paket kayıpları yaşandı.
- Bağlantı geri açıldıktan sonra iletişim doğrulandı.
- 295 kayıt FAILURE olarak etiketlendi.

## 5. Veri Kalitesi
- Toplam 6373 kayıt ve 31 sütun.
- Tekrarlanan zaman-switch-port anahtarı: 0.
- throughput_mbps alanı: %100 dolu.
- latency_ms alanı: %100 boş.
- e2e_loss_percent alanı: %100 boş.
- declared_load_mbps alanı: %100 boş.
- Sınıf dağılımı dengesiz.
- Her sınıf tek etiketli deney oturumuyla temsil ediliyor.
- Etiketler port bazlı arıza kanıtı değil,
  deney aralığındaki ağ durumunu ifade ediyor.
- Ping özetleri port satırlarına doğrudan eşleştirilmedi.

## 6. Otomatik Testler
Komut:
`python3 -m pytest -q tests/ deneyler/tests/`

Sonuç:
- 90 test başarılı.
- 0 test başarısız.
- 2 bağımlılık uyarısı.

## 7. Sınırlılıklar
- Gecikme ve uçtan uca kayıp henüz satır bazında yok.
- Bağımsız tekrar deneyleri gerekli.
- Deney kimliği model özelliği olarak kullanılmamalı.
- Model eğitimi öncesinde bağımsız deneylerle
  doğrulama planlanmalı.

## 8. Doğrulama notları (24 Kasım 2026)

Bu rapor, depodaki dosyalarla yeniden karşılaştırılmıştır:

- Kayıt sayıları, sütun sayısı, tekrar anahtarı (0), boş alan oranları ve 4 switch birleşik CSV'den yeniden hesaplanıp doğrulanmıştır.
- FAILURE satırlarının yalnızca 5'inde `link_up=0` ve `admin_up=0` vardır (kapatılan tek port, ≈25 sn); kalan 290 satır aynı deney aralığındaki diğer portlardır. Etiket aralık düzeyindedir.
- `controller.log` zaman damgası taşımadığından, FAILURE bölümündeki "alternatif yol kurma ve failback olayları" ifadesi bu pencereye kesin olarak eşlenememiştir; günlükte aynı oturumda `PATH_ACTIVE` ve `FAILBACK_COMPLETE` bulunur, ancak son kayıtlarda `RECOVERY SKIPPED` ve `NO_ALTERNATIVE_PATH` da vardır.
- "Bağlantı geri açıldıktan sonra iletişim doğrulandı" ve FAILURE sırasındaki kayıp sayısı için depoda ping çıktısı yoktur; yalnızca açma/kapama zamanları (`failure_t1_down.txt`, `failure_t1_up.txt`) kayıtlıdır.
- LOAD sınıfındaki en yüksek throughput ≈0,338 Mbps'tir (hafif yük).

## 9. Sonuç
Aşama 9 kapsamında dört ağ durumuna ait veri
toplama, etiketleme, birleştirme ve temel kalite
kontrolü gerçekleştirilmiştir.

Eksik ölçümler ve deney sınırlılıkları belgelenmiştir.
Bu rapor yapay zekâ modelinin eğitildiğini veya
canlı ağda kusursuz kurtarma sağlandığını iddia etmez.
