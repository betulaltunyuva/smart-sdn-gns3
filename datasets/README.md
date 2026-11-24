# Aşama 9 – İzleme Verisi ve Veri Seti Oluşturma

Aşama 10'daki AI/Anomaly Agent için port bazlı bir CSV veri seti toplanır. Bu aşamada **yapay zekâ modeli yoktur**; yalnızca veri toplama ve etiketleme altyapısı vardır.

| Dosya | Görev |
|:--|:--|
| `utils/dataset_collector.py` | `PORT_METRICS` (+ `LINK_UP/LINK_DOWN`) olaylarını CSV'ye yazar (EventBus gözlemcisi) |
| `utils/dataset_labels.py` | Etiket kuralları + doğrulanmış anotasyonlarla çevrimdışı etiketleme |
| `tests/test_dataset_collector_offline.py` | GNS3 gerektirmeyen testler |

Monitoring, Failure, Routing ve Recovery Agent'lara dokunulmamıştır. `controller/sdn_controller.py`'de yalnızca guard'lı bir import ve toplayıcıyı kuran birkaç satır vardır.

## 1. Veri toplama

**Varsayılan olarak KAPALIDIR.** Controller'ı ortam değişkenleriyle başlatın:

```bash
SDN_DATASET=1 \
SDN_DATASET_EXPERIMENT=normal_t1 \
SDN_DATASET_LABEL=UNKNOWN \
./start_sdn.sh        # veya: osken-manager --observe-links controller/sdn_controller.py
```

| Değişken | Anlamı | Varsayılan |
|:--|:--|:--|
| `SDN_DATASET` | `1/true/yes/on` ise açık | kapalı |
| `SDN_DATASET_PATH` | CSV yolu (klasör otomatik oluşur) | `datasets/port_metrics.csv` |
| `SDN_DATASET_EXPERIMENT` | Deney/senaryo kimliği | `run-<UTC başlangıç>` |
| `SDN_DATASET_LABEL` | `NORMAL/LOAD/CONGESTION/FAILURE/UNKNOWN` | `UNKNOWN` |
| `SDN_DATASET_LOAD_MBPS` | Operatörün **bildirdiği** uygulanan yük | boş |
| `SDN_DATASET_MAX_MB` | Bu boyutta dosya döndürülür | 50 |

Çalışma biçimi:
- Her `PORT_METRICS` (5 sn'de bir, port başına) bir satırdır. Controller'ın ilk poll'ü *baseline* olduğundan o örnek için satır yoktur (MonitoringAgent hız üretemez).
- Kopya koruması: aynı port için içerik aynı ve <1 sn aralıklı tekrar teslim yazılmaz. Boşta bir portun 5 sn sonraki gerçek örneği **yazılır**.
- Başlık tutarlıdır; dosya varsa satırlar eklenir. Başlığı farklı eski bir dosya **değiştirilmez**, zaman damgalı yeni dosyaya yazılır.
- Hata güvenliği: disk/yazma hatası controller'ı etkilemez; art arda 5 hatada toplayıcı kendini kapatır.
- Uzun süre: dosya `SDN_DATASET_MAX_MB`'a ulaşınca `port_metrics.<UTC>.csv` adıyla döndürülür. Her satır flush edilir (5 sn'de bir yazma, ihmal edilebilir yük).
- `datasets/*.csv` zaten `.gitignore`'dadır.

## 2. CSV alanları

Zaman: `timestamp_utc` = satırın toplayıcıya ulaştığı **controller saatinin** UTC değeri (`YYYY-MM-DDTHH:MM:SS.mmmZ`). Switch tarafı örnek zamanı değildir; `interval_sec` switch port süresinden hesaplanır.

| Alan | Birim / değer | Kaynak |
|:--|:--|:--|
| `timestamp_utc` | UTC ISO-8601 | toplayıcı |
| `experiment_id` | metin | operatör (env) |
| `label`, `label_source` | `NORMAL/LOAD/CONGESTION/FAILURE/UNKNOWN`; `none`, `operator_env`, `annotation:<kanıt>`, `conflict` | bkz. §3 |
| `dpid`, `dpid_hex` | ondalık / 16 hane hex | OpenFlow |
| `port_no`, `port_name` | OpenFlow port no / ad (ör. `eth1`) | PortDesc |
| `link_up` | 1/0, boş=bilinmiyor | PortDesc `OFPPS_LINK_DOWN` (**fiziksel port durumu**) |
| `admin_up` | 1/0 | PortDesc `OFPPC_PORT_DOWN` |
| `isl_port` | 1=LLDP ile switchler arası link görüldü, 0=LLDP link kaybı görüldü, boş=bilinmiyor | `LINK_UP/DOWN` olayları |
| `interval_sec` | saniye | MonitoringAgent |
| `rx_bytes tx_bytes rx_packets tx_packets` | kümülatif sayaç | PortStats |
| `rx_errors tx_errors rx_dropped tx_dropped` | kümülatif sayaç | PortStats |
| `rx_bytes_per_sec tx_bytes_per_sec` | bayt/sn | iki örnek farkı |
| `rx_mbps tx_mbps` | Mbps | iki örnek farkı |
| `throughput_mbps` | Mbps = rx+tx (iki yön toplamı) | MonitoringAgent |
| `rx_pps tx_pps` | paket/sn | iki örnek farkı |
| `packet_rate_pps` | paket/sn = rx+tx | MonitoringAgent |
| `latency_ms` | ms | **ÖLÇÜLMÜYOR – her zaman boş** |
| `e2e_loss_percent` | % | **ÖLÇÜLMÜYOR – her zaman boş** |
| `declared_load_mbps` | Mbps | operatörün bildirdiği değer, **ölçüm değil** |

Boş hücre = "ölçülemedi / bilinmiyor"; `0` = gerçekten sıfır. Desteklenmeyen sayaç (`0xffff…`), negatif, NaN/∞ veya yanlış tipli değerler boş yazılır. Sayaç sıfırlanması (switch yeniden bağlanması) MonitoringAgent'ta yeni baseline olur, bu örnek için satır yazılmaz.

### Doğrudan alınabilenler / ek ölçüm gerekenler

| Durum | Alanlar |
|:--|:--|
| Sistemden doğrudan | tüm sayaçlar, hızlar, `interval_sec`, `link_up`, `admin_up`, `port_name`, `dpid`, `isl_port`, zaman |
| Operatör bildirimi | `experiment_id`, `label`, `declared_load_mbps` |
| **Ek ölçüm gerekli (şu an boş)** | `latency_ms`, `e2e_loss_percent` (uçtan uca ping/iperf kaydından türetilip zamana göre eşlenmeli), gerçek kuyruk doluluğu, link kapasitesi (kullanım yüzdesi için) |

Port hızı/kapasitesi PortDesc'te var ama şu an PORT_METRICS'e taşınmıyor; kullanım yüzdesi için Aşama 9.4'te değerlendirilebilir (agent değiştirmeden).

## 3. Etiketleme yöntemi

Etiketler **ölçümden türetilmez**. Kural: etiket yalnızca operatörün doğruladığı deney senaryosuna aittir.

1. Ham toplama sırasında etiket `UNKNOWN` bırakılır (veya tek etiketli çalışmalar için `SDN_DATASET_LABEL` ile operatör verir → `label_source=operator_env`).
2. Deney sonrası, doğrulanmış aralıkları içeren **anotasyon CSV'si** hazırlanır:

```csv
experiment_id,start_utc,end_utc,label,evidence_type,evidence_note
baglanti_kopmasi_t1,2026-11-23T10:00:00Z,2026-11-23T10:05:00Z,NORMAL,baseline_no_fault,Yük/arıza yok
baglanti_kopmasi_t1,2026-11-23T10:05:00Z,2026-11-23T10:07:00Z,FAILURE,physical_link_down,GNS3'te SW1-SW2 linki Suspend edildi 10:05:02
```

3. Etiketleme (ham dosyaya dokunmaz, var olan çıktının üzerine yazmaz):

```bash
python3 -m utils.dataset_labels datasets/port_metrics.csv anotasyon.csv -o datasets/port_metrics_labeled.csv
```

Aralık: `[start, end)`. Aralık dışı, başka deney veya çelişen aralıklar → `UNKNOWN`.

| Etiket | Kabul edilen `evidence_type` | Not |
|:--|:--|:--|
| `NORMAL` | `baseline_no_fault` | Hata ve yük yok |
| `LOAD` | `traffic_generator` | Bilinen yük üretildi, tıkanıklık kanıtı yok |
| `CONGESTION` | `e2e_loss`, `latency_increase`, `drop_counters` | Yüksek Mbps tek başına yetmez; uçtan uca kayıp/gecikme artışı veya drop artışı ayrıca ölçülmeli |
| `FAILURE` | `physical_link_down`, `port_admin_down`, `node_stopped` | Arıza bilerek ve doğrulanarak uygulanmış olmalı |

**Reddedilen kanıtlar:** `zero_traffic`, `lldp_loss`, `link_removed_event`. Trafiğin sıfır olması FAILURE değildir (ağ boşta olabilir); LLDP link kaybı fiziksel arıza kanıtı değildir (LLDP paket kaybı, timeout vb. nedenlerle de olabilir). Geçersiz anotasyon varsa araç hiçbir çıktı yazmadan hata verir.

## 4. Testler

```bash
python3 -m unittest -v tests.test_dataset_collector_offline
# tüm offline testler:
python3 -m unittest tests.test_failure_agent_offline tests.test_recovery_agent_offline \
  tests.test_routing_agent_offline tests.test_runtime_state_offline tests.test_dataset_collector_offline
```

## 5. Durum (24 Kasım 2026) ve sonraki adımlar

**Yapılanlar:** NORMAL (4189), LOAD (590), CONGESTION (1299) ve FAILURE (295) senaryoları toplanıp etiketlenmiş, birleştirilmiştir: `stage9_birlesik_etiketli.csv` (6373 satır, 31 sütun). Anotasyonlar `annotations_*.csv`, kalite raporu `stage9_kalite_raporu.txt`, ping/`tc` özetleri `*.txt` dosyalarındadır. Ayrıntı: `deneyler/ASAMA_9_VERI_SETI_RAPORU.md`.

**Depoda yalnızca** birleşik veri seti, anotasyonlar, kalite raporu ve küçük metin kanıtları bulunur; ham/ara CSV'ler (`*_ham_kopya`, `*_ayrilmis`, `*_test_araligi`, `port_metrics.csv`, yedekler; toplam ≈73 MB) `.gitignore` nedeniyle yerelde kalır.

**Bilinen eksikler:** `latency_ms`, `e2e_loss_percent`, `declared_load_mbps` boş; sınıflar dengesiz; her sınıf tek deneyle temsil edilir; etiketler deney aralığı düzeyindedir; `experiment_id` / `label_source` model özelliği olarak kullanılmamalıdır.

**Sonraki adımlar (başlanmadı):**

1. Zaman damgalı ping/iperf kaydından `latency_ms` ve `e2e_loss_percent` türetip `timestamp_utc` ile eşleme.
2. Her sınıf için bağımsız tekrar deneyleri; daha yüksek yüklü LOAD deneyi.
3. Aşama 10'a (AI/anomali ajanı) geçmeden önce doğrulama planı.
