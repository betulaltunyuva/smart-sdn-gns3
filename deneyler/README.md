# Aşama 8.5 – Tekrarlı Deney ve Performans Analizi

Bu klasördeki araçlarla PC1 (`10.0.0.1`) ile PC2 (`10.0.0.2`) arasındaki ping deneyleri 4 senaryo × 3 tekrar olarak kaydedilir ve analiz edilir. Kodda yalnızca Python 3 standart kütüphanesi kullanılır; yeni bir bağımlılık eklenmez.

> **Araçlar ağa dokunmaz.** Ping göndermez, VPCS konsoluna bağlanmaz, Controller'ı, Docker'ı veya GNS3'ü başlatıp durdurmaz. `controller/`, `agents/`, `dashboard/` ve `start_sdn.sh` dosyalarında değişiklik yapılmamıştır.

## 1. Veri toplama yöntemi ve gerekçesi

Mevcut sistem salt okunur olarak incelendi (21 Kasım 2026):

| Bulgu | Sonuç |
|:--|:--|
| PC1: `vpcs -p 5000 ... -s 10064 -c 10065`, PC2: `vpcs -p 5001 ... -s 10066 -c 10067` | Konsol 5000/5001, ağ trafiği UDP tüneli üzerinden ubridge'e gidiyor |
| `127.0.0.1:5000` ve `5001` bağlantıları `gns3server` sürecine ait | VPCS konsolu **tek istemci** kabul ediyor ve bu istemci GNS3 Server |
| 5000 dinleme kuyruğunda kabul edilmemiş bağlantılar ve `CLOSE-WAIT` oturumlar var | telnetlib'in veri alamamasının nedeni bu. İkinci istemci kuyrukta bekliyor. |
| `tcpdump` parola ile `sudo` gerektiriyor; `tshark` kurulu değil | Paket yakalama yalnızca kullanıcının kendisi başlatırsa mümkün |
| `logs/controller.log` satırlarında zaman damgası yok; `runtime/state.json` → `incidents[].steps[].t` epoch zamanı içeriyor | Controller tepki süresi `state.json` **kopyasından** hesaplanır |

**Karar:** Konsola otomatik komut gönderme yöntemi **kullanılmadı**. Bunun için GNS3 Server'ın bağlantısını kesmek ya da kullanıcının oturumuna müdahale etmek gerekirdi.

- **Yöntem A (birincil): VPCS metin kaydı.** Ping, GNS3 konsolundan elle başlatılır ve çıktı, şablon dosyasına yapıştırılır. Paket sayıları ve RTT değerleri kesindir. Kayıtta zaman damgası olmadığından kesinti süresi yalnızca tahmin edilebilir.
- **Yöntem B (isteğe bağlı): pcap.** PC1'in UDP tüneli `lo` arayüzünde `sudo tcpdump` ile yakalanır. Analizci, UDP yükündeki Ethernet çerçevesini açarak ICMP echo request ve reply çiftlerini bulur ve zaman damgalarını kullanır. **pcap'te `10.0.0.1 → 10.0.0.2` echo request bulunmazsa ölçüm üretilmez** ve araç metin kaydına geri döner.

## 2. Hesaplanan ölçümler

| Alan | Tanım |
|:--|:--|
| `gonderilen_paket` | Sonucu kayıtta bulunan seq sayısı (yanıt + timeout + ICMP hata) |
| `basarili_paket` / `kayip_paket` | Yanıt alınan seq'ler / **açıkça** `timeout` ya da ICMP hata ile biten seq'ler |
| `eksik_seq_sayisi` | `1..beklenen` aralığında kayıtta hiç görünmeyen seq'ler. **Kayıp sayılmaz**; ölçüm `BELIRSIZ` olarak işaretlenir |
| `kayip_yuzde` | `kayip_paket / gonderilen_paket × 100`. Eksik seq varsa `kayip_alt_yuzde` ve `kayip_ust_yuzde` sınırları da verilir |
| `rtt_min/max/ort/medyan_ms` | Yanıtlanan paketlerin RTT değerleri |
| `rtt_p95_ms` | **En yakın sıra (nearest-rank):** sıralı RTT listesinin `ceil(0,95·n)`. elemanı |
| `jitter_ms` | Ardışık seq numaralı `(i, i+1)` paketlerin **ikisi de** yanıtlandığında `|RTT(i+1) − RTT(i)|` değerlerinin ortalaması (RFC 3393 IPDV'nin mutlak değer ortalaması; RFC 3550'deki üstel yumuşatma uygulanmaz). Kayıp boşluğunu aşan çiftler hesaba katılmaz. `rtt_std_ms` ayrıca verilir |
| `en_uzun_kayip_patlamasi` | Art arda kaybolan paketlerin en uzun dizisi. Metin kaydında kesintinin **kesin** ölçüsüdür |
| `kesinti_nominal_s` | `en_uzun_kayip_patlamasi × aralık`. **Tahmindir** (± 1 ping aralığı) |
| `kesinti_olculen_s` | Yalnızca pcap ile hesaplanır: kesintiden önceki son yanıt ile sonraki ilk yanıt arasındaki süre |
| `oncesi_*` / `sonrasi_*` | Arıza veya olay öncesi ve sonrası RTT karşılaştırması. Bölme noktası en uzun kayıp patlaması ya da `olay_ping` başlığıdır |

### Controller tepki süresi ≠ uçtan uca kesinti

| Ölçüm | Kaynak | Anlamı |
|:--|:--|:--|
| `ctrl_tespit_path_active_ms` | `state.json` `DETECTED → PATH_ACTIVE` | Controller'ın `LINK_DOWN` olayını görmesinden kurtarma kurallarının etkinleşmesine kadar geçen süre. **Linkin fiziksel olarak kopmasından tespite kadar geçen süreyi içermez.** |
| `ctrl_linkup_failback_baslangic_ms` | `LINK_UP → FAILBACK_START` | Bilinçli olarak eklenen `FAILBACK_STABLE_SECONDS = 10` s kararlılık beklemesini içerir |
| `ctrl_failback_islem_ms` | `FAILBACK_START → FAILBACK_COMPLETE` | Kurtarma kurallarının temizlenmesi |
| `en_uzun_kayip_patlamasi`, `kesinti_*` | Ping kaydı / pcap | Kullanıcının yaşadığı uçtan uca iletişim kesintisi |
| `path_active_ilk_yanit_ms` | pcap + state (aynı saat) | `PATH_ACTIVE` anından sonra gelen ilk ICMP yanıtına kadar geçen süre |

Metin kaydında zaman damgası olmadığından Controller olayı ping kaydıyla zamansal olarak eşleştirilemez. Bu durumda state kopyasındaki son ilgili olay kullanılır ve `notlar` sütununa bu durum yazılır. Bu nedenle `state-kopyala` komutu **her deneyden hemen sonra** çalıştırılmalıdır. `state.json` yalnızca son 20 olayı tuttuğu için sonradan alınan kopyada deneye ait olay bulunmayabilir.

## 3. Deney planı (4 senaryo × 3 tekrar)

| # | Senaryo (`dosya öneki`) | Uygulama | Başarı ölçütü |
|:--:|:--|:--|:--|
| 1 | Normal (`normal`) | Topoloji 4/4 iken `ping 10.0.0.2 -c 100` | Kayıp = 0 |
| 2 | Bağlantı kopması (`baglanti_kopmasi`) | Ping sırasında (~30. pakette) OVS-1↔OVS-2 linkine **Suspend** uygulanır, link kopuk bırakılır | Son paket yanıtlanmış olmalı (iletişim yeniden kurulmalı). Kesinti ve Controller süresi raporlanır |
| 3 | Otomatik kurtarma (`otomatik_kurtarma`) | Link hâlâ kopukken ve `PATH_ACTIVE` etkinken `ping -c 100` | Alternatif yolda kayıp = 0. RTT normal senaryoyla karşılaştırılır |
| 4 | Failback (`failback`) | Ping sırasında (~30. pakette) link için **Resume** yapılır. Resume'dan sonra en az ~15 s ping sürmelidir | Son paket yanıtlanmış olmalı. Failback sırasındaki kayıp ve sonraki RTT raporlanır |

Durum kodları: `BASARILI`, `BASARISIZ` (ölçüt sağlanmadı) ve `BELIRSIZ` (eksik seq, aynı seq'in birden fazla görülmesi veya boş kayıt nedeniyle ölçüm güvenilmez).

## 4. Adım adım kullanım (proje kökünden)

```bash
python3 deneyler/experiment_runner.py plan                       # plan + hangi kayıtlar hazır
python3 deneyler/experiment_runner.py yeni baglanti_kopmasi 1    # şablon: ham_veri/baglanti_kopmasi_t1.txt
#   -> PC1 GNS3 konsolunda: ping 10.0.0.2 -c 100 (senaryo adımlarını uygulayın)
#   -> Çıktının tamamını (ping komutu satırı dahil) şablonun altına yapıştırın,
#      Suspend/Resume anındaki seq'i "# olay_ping:" satırına yazın
python3 deneyler/experiment_runner.py state-kopyala baglanti_kopmasi 1   # hemen ardından
python3 deneyler/experiment_runner.py analiz          # tüm kayıtlar -> CSV + SVG
python3 deneyler/experiment_runner.py analiz -v       # ayrıntılı rapor
```

Tek bir dosyayı analiz etmek ve yalnızca Controller olaylarını listelemek için:

```bash
python3 deneyler/ping_analyzer.py deneyler/ham_veri/normal_t1.txt
python3 deneyler/ping_analyzer.py --controller-olaylari deneyler/ham_veri/baglanti_kopmasi_t1_state.json
```

Var olan bir dosyanın üzerine yazılmaz; `yeni` ve `state-kopyala` komutları bu durumda işlemi reddeder.

### İsteğe bağlı: pcap ile zaman damgalı ölçüm

```bash
python3 deneyler/experiment_runner.py portlar    # güncel UDP portlarını ve tcpdump komutunu yazdırır
# Ayrı terminalde, ping'ten ÖNCE başlatın (parola istenir), ping bitince Ctrl+C:
sudo tcpdump -i lo -U -Z $USER -w deneyler/ham_veri/baglanti_kopmasi_t1.pcap 'udp port 10064 or udp port 10065'
```

İlk kullanımdan önce 5 pinglik bir deneme yakalaması yapın ve `python3 deneyler/ping_analyzer.py --pcap deneme.pcap` komutuyla `beklenen=5` sonucunun görüldüğünü doğrulayın. Aynı adlı `.pcap` dosyası bulunduğunda analiz pcap'i birincil kaynak olarak kullanır, metin kaydını ise çapraz kontrol için kullanır.

## 5. Çıktılar (`deneyler/sonuclar/`)

| Dosya | İçerik |
|:--|:--|
| `deney_sonuclari.csv` | Her deney için bir satır: ad, tarih, senaryo, tekrar, veri kaynağı, `veri_turu`, durum, paket ve kayıp değerleri, RTT/P95/jitter, kesinti, önce/sonra karşılaştırması, Controller süreleri ve notlar |
| `senaryo_ozeti.csv` | Senaryo bazında tekrarların `n`, ortalama, standart sapma, minimum ve maksimum değerleri |
| `grafik_*.svg` | Kayıp %, ortalama RTT, P95 RTT, jitter ve en uzun kesinti. Senaryo başına çubuk tekrar ortalamasını, noktalar ise tek tek tekrarları gösterir |

CSV dosyaları virgül ayraçlı, ondalık ayracı nokta olan UTF-8 dosyalardır. Özet ve grafiklere yalnızca `veri_turu=GERCEK_OLCUM` olan kayıtlar alınır. Şablonda `# veri_turu: ornek` yazan kayıtlar yalnızca `deney_sonuclari.csv` dosyasında `ORNEK` olarak görünür.

## 6. Testler

```bash
python3 -m unittest discover -v -s deneyler/tests
```

27 test bulunur. Testlerdeki tüm ping kayıtları, pcap'ler ve state dosyaları **sentetik** verilerdir ve geçici dizinlerde üretilir. Testler şunları kapsar: istatistik tanımları, açık timeout ile eksik seq ayrımı, kesik ya da çift oturumlu kayıtlar, ICMP hata/DUP/farklı hedef/bozuk satırlar, UDP tüneli ve VLAN'lı pcap, ICMP içermeyen yakalamanın reddedilmesi, Controller zamanlamaları, dosyaların üzerine yazmama davranışı ve CSV/SVG doğrulaması.

## 7. Sınırlar

- Metin kaydında zaman damgası yoktur. Bu nedenle kesinti süresi paket sayısı ve nominal aralıktan tahmin edilir. VPCS'te timeout bekleme süresi ile gönderim aralığı birlikte etkili olabildiğinden gerçek süre farklı olabilir. Kesin süre için pcap kullanılmalıdır.
- Gerçek ağda pcap yöntemi henüz doğrulanmamıştır; tcpdump `sudo` gerektirdiği için doğrulama kullanıcı tarafından yapılmalıdır.
- Aşama 8.1–8.4 sonuçları için ham ping çıktısı saklanmamıştır. `ASAMA_8_DENEY_SONUCLARI.md` yalnızca özet değerleri içerdiğinden medyan, P95 ve jitter bu deneyler için **geriye dönük olarak hesaplanamaz**.
