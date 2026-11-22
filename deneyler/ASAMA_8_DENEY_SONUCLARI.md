# AŞAMA 8 – SELF-HEALING DENEY SONUÇLARI

**Proje:** Smart SDN Multi-Agent Self-Healing Network  
**Tarih:** 21 Kasım 2026  
**Test ortamı:** GNS3, Open vSwitch, OpenFlow 1.3, OS-Ken Controller

## 1. Deneylerin Amacı

Bu deneylerin amacı, geliştirilen SDN ağının bağlantı arızalarını algılama, alternatif yol hesaplama, trafiği yeniden yönlendirme ve arıza giderildikten sonra normal çalışma durumuna dönme yeteneklerini değerlendirmektir.

Testlerde PC1 (10.0.0.1) ile PC2 (10.0.0.2) arasındaki iletişim incelenmiştir.

## 2. Aşama 8.1 – Normal Ağ Performansı

**Senaryo:** Ağda herhangi bir bağlantı kesilmeden PC1'den PC2'ye ping gönderilmiştir.

**Komut:** `ping 10.0.0.2 -c 20`

**Sonuçlar:**
- Gönderilen paket: 20
- Alınan yanıt: 20
- Paket kaybı: %0
- En düşük gecikme: 3,089 ms
- En yüksek gecikme: 72,380 ms

Ek olarak 100 pinglik bir başlangıç testi gerçekleştirilmiştir. Çoğu yanıt yaklaşık 3–6 ms aralığında gelmiş, bazı paketlerde 303,734 ms ve 719,441 ms gecikmeler gözlemlenmiştir.

**Değerlendirme:** Normal koşullarda PC1 ile PC2 arasında iletişim sağlanmıştır. Gecikme sıçramalarının nedenleri sonraki testlerde araştırılacaktır.

## 3. Aşama 8.2 – Bağlantı Arızası ve Otomatik Kurtarma

**Senaryo:** PC1 ile PC2 arasında ping devam ederken GNS3 üzerinde OpenvSwitch-1 ile OpenvSwitch-2 arasındaki bağlantı Suspend işlemiyle kesilmiştir.

**Komut:** `ping 10.0.0.2 -c 100`

**Gözlemler:**
- İlk 30 ping yanıtı başarıyla alınmıştır.
- 31–35 numaralı pinglerde art arda 5 timeout gözlemlenmiştir.
- 36. pingden itibaren iletişim yeniden başlamıştır.
- Controller loglarında `FLOW_INSTALLED` ve `PATH_ACTIVE` kayıtları görülmüştür.

**Değerlendirme:** Bağlantı arızası sırasında geçici iletişim kaybı oluşmuş, ardından trafik yeniden iletilebilmiştir. Recovery Agent'ın alternatif yol için OpenFlow kuralları oluşturduğu da loglarda gözlemlenmiştir.

**Not:** Beş ardışık timeout doğrulanmıştır. Bunun 100 paketlik testin toplam kayıp sayısı olduğu henüz kesinleştirilmemiştir.

## 4. Aşama 8.3 – Failback (Normal Yönlendirmeye Dönüş)

**Senaryo:** Suspend edilen bağlantı GNS3 üzerinden Resume işlemiyle yeniden etkinleştirilmiştir.

**Loglarda gözlemlenen olaylar:**
- `FAILBACK_PENDING`
- `FAILBACK_START`
- `RECOVERY_FLOWS_REMOVED`
- `FAILBACK_COMPLETE`

Loglarda kurtarma kurallarının kaldırıldığına ilişkin `removed=32/32` kayıtları görülmüştür.

**Bağlantı geri açıldıktan sonraki ping testi:**

**Komut:** `ping 10.0.0.2 -c 20`

**Sonuçlar:**
- Gönderilen paket: 20
- Alınan yanıt: 20
- Paket kaybı: %0
- En düşük gecikme: 2,751 ms
- En yüksek gecikme: 31,955 ms

**Değerlendirme:** Sistem loglarında normal yönlendirmeye dönüş işlemleri gözlemlenmiş ve bağlantı yeniden açıldıktan sonra PC1–PC2 iletişiminin başarılı olduğu doğrulanmıştır.

## 5. Genel Değerlendirme

İlk üç deneyde SDN ağının normal iletişim, bağlantı arızasından sonra yeniden iletişim kurma ve bağlantı onarıldığında normal çalışmaya dönme davranışları incelenmiştir.

Controller logları ile ping sonuçları, geliştirilen self-healing mekanizmasının beklenen işlevleri yerine getirdiğine dair kanıt sağlamaktadır.

**Önemli:** Dashboard'da gösterilen Controller tepki süresi, gerçek uçtan uca paket kesintisi süresiyle aynı değildir. Kesin kurtarma süresi ve toplam paket kaybı oranı için zaman damgalı, tekrarlı deneyler yapılacaktır.

## 6. Sonraki Deneyler

- **Aşama 8.4:** Switch arızası ve alternatif yol bulunamaması
- **Aşama 8.5:** Tekrarlı deneyler ve performans karşılaştırmaları
- **Aşama 8.6:** Sonuçların raporlanması ve GitHub'a kaydedilmesi
## 7. Aşama 8.4 – Switch Arızası ve Ağın Yeniden Toparlanması

**Deney tarihi:** 21 Kasım 2026

### Deneyin Amacı

Bu deneyde, SDN ağındaki bir Open vSwitch cihazının devre dışı kalması durumunda sistemin arızayı nasıl algıladığı, alternatif yolları nasıl değerlendirdiği ve cihaz yeniden başlatıldığında ağın normal durumuna dönüp dönmediği incelenmiştir.

### Deneyin Uygulanması

1. PC1 (10.0.0.1) üzerinden PC2'ye (10.0.0.2) 300 pinglik test başlatılmıştır.
2. Ping devam ederken GNS3 üzerinde OpenvSwitch-3 durdurulmuştur.
3. Controller kayıtları incelenerek bağlantı arızasının algılanması ve alternatif yol hesaplamaları kontrol edilmiştir.
4. OpenvSwitch-3 yeniden başlatılmıştır.
5. Yönetim IP adresi tekrar alınarak Controller bağlantısı sağlanmıştır.
6. Ağ topolojisi ve PC1–PC2 iletişimi yeniden doğrulanmıştır.

### Gözlemlenen Sonuçlar

| Kontrol | Sonuç |
|---|---|
| OpenvSwitch-3 durduruldu | Başarılı |
| Docker durumu | Exited (137) |
| Controller bağlantı arızalarını algıladı | Başarılı |
| Alternatif yollar değerlendirildi | Başarılı |
| NO_ALTERNATIVE_PATH olayı | Bazı bağlantılar için gözlemlendi |
| PC1–PC2 iletişimi | Görüntülenen pinglerde devam etti |
| OpenvSwitch-3 yeniden başlatıldı | Başarılı |
| Yönetim IP adresi | 192.168.122.254 |
| Controller bağlantısı | is_connected: true |
| Yeniden keşfedilen topoloji | 4 switch, 4 bağlantı |

### Son İletişim Testi

OpenvSwitch-3 yeniden başlatıldıktan sonra aşağıdaki komut çalıştırılmıştır:

`ping 10.0.0.2 -c 20`

**Sonuçlar:**
- Gönderilen paket: 20
- Başarılı yanıt: 20
- Paket kaybı: %0
- En düşük gecikme: 3,597 ms
- En yüksek gecikme: 407,172 ms

### Değerlendirme

Deney sırasında Controller'ın bağlantı kayıplarını algıladığı ve Routing Agent'ın alternatif yolları değerlendirdiği gözlemlenmiştir.

OpenvSwitch-3 devre dışıyken PC1–PC2 iletişiminin devam ettiği görülmüştür. Ancak bu sonuç, tek başına trafiğin Recovery Agent tarafından yeniden yönlendirildiğini kanıtlamaz; iletişim mevcut başka bir yol üzerinden sürmüş olabilir.

OpenvSwitch-3 yeniden başlatıldıktan sonra Controller bağlantısı sağlanmış ve ağ topolojisi dört switch ile dört bağlantı içerecek şekilde yeniden keşfedilmiştir.

Son 20 ping testinde paket kaybı görülmemiştir. Bununla birlikte bazı paketlerde yüksek gecikmeler gözlemlenmiştir.

**Önemli not:** Bu deneyde bazı bağlantılar için NO_ALTERNATIVE_PATH kaydı oluşmuştur. Ancak PC1 ile PC2 arasında hiçbir alternatif yolun kalmadığı durum henüz bağımsız bir deneyle doğrulanmamıştır.

**Sonuç:** Switch arızası sonrasında ağın bağlantı kayıplarını algıladığı, PC1–PC2 iletişiminin gözlemlenen bölümde devam ettiği ve cihaz yeniden başlatıldığında topolojinin normal durumuna dönebildiği doğrulanmıştır.
