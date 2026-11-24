"""
Smart SDN (GNS3) - Aşama 9.2: PORT_METRICS -> CSV veri seti toplayıcı

MonitoringAgent'ın yayınladığı PORT_METRICS olaylarını (ve link durumu için
LINK_UP / LINK_DOWN olaylarını) dinler; her port örneğini tek satır olarak
bir CSV dosyasına ekler. Yalnızca standart kütüphane kullanılır.

Tasarım ilkeleri:
  * Salt gözlemcidir: hiçbir agent davranışını değiştirmez, EventBus'a
    olay yayınlamaz. Her callback try/except ile korunur; disk hatası
    controller'ı etkilemez (art arda hatada toplayıcı kendini kapatır).
  * Varsayılan KAPALIDIR. Ortam değişkeni SDN_DATASET=1 ile açılır.
  * Ölçülmeyen alanlar (latency_ms, e2e_loss_percent) ASLA üretilmez;
    hücre boş bırakılır. Geçersiz/eksik sayaçlar da boş yazılır.
  * Etiket yalnızca operatörün açıkça verdiği değerdir (varsayılan
    UNKNOWN); trafiğe bakılarak etiket türetilmez. Ayrıntı:
    utils/dataset_labels.py ve datasets/README.md.

Ortam değişkenleri:
  SDN_DATASET            "1"/"true"/"yes"/"on" ise toplama açılır
  SDN_DATASET_PATH       CSV yolu (varsayılan datasets/port_metrics.csv)
  SDN_DATASET_EXPERIMENT deney/senaryo kimliği (varsayılan: başlangıç
                         zamanından üretilen "run-YYYYmmddTHHMMSSZ")
  SDN_DATASET_LABEL      NORMAL|LOAD|CONGESTION|FAILURE|UNKNOWN
                         (varsayılan UNKNOWN; geçersiz değer -> UNKNOWN)
  SDN_DATASET_LOAD_MBPS  operatörün uyguladığı yük (Mbps, bildirimsel);
                         boşsa alan boş kalır
  SDN_DATASET_MAX_MB     dosya bu boyuta ulaşınca döndürülür (varsayılan 50)
"""

import csv
import datetime
import logging
import math
import os

from utils.event_bus import PORT_METRICS, LINK_UP, LINK_DOWN
from utils.dataset_labels import LABELS, UNKNOWN

DEFAULT_PATH = os.path.join("datasets", "port_metrics.csv")
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
# Aynı port için aynı içerik bu süreden kısa aralıkla (monotonic sn) tekrar
# gelirse kopya sayılır. Gerçek örnekler STATS_INTERVAL (5 sn) aralıklıdır.
DEDUP_WINDOW_SEC = 1.0
MAX_CONSECUTIVE_ERRORS = 5

COLUMNS = (
    "timestamp_utc", "experiment_id", "label", "label_source",
    "dpid", "dpid_hex", "port_no", "port_name",
    "link_up", "admin_up", "isl_port",
    "interval_sec",
    "rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
    "rx_errors", "tx_errors", "rx_dropped", "tx_dropped",
    "rx_bytes_per_sec", "tx_bytes_per_sec",
    "rx_mbps", "tx_mbps", "throughput_mbps",
    "rx_pps", "tx_pps", "packet_rate_pps",
    "latency_ms", "e2e_loss_percent", "declared_load_mbps",
)

_COUNTERS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
             "rx_errors", "tx_errors", "rx_dropped", "tx_dropped")
_RATES = (("rx_bytes_per_sec", "rx_bytes_per_sec"),
          ("tx_bytes_per_sec", "tx_bytes_per_sec"),
          ("rx_mbps", "rx_mbps"), ("tx_mbps", "tx_mbps"),
          ("throughput_mbps", "throughput_mbps"),
          ("rx_pps", "rx_pps"), ("tx_pps", "tx_pps"),
          ("packet_rate_pps", "packet_rate"))   # (sütun, payload anahtarı)


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _int_or_blank(value):
    """Negatif olmayan tam sayı sayaç; aksi halde boş (ölçülemedi)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return ""
    if value < 0 or value == 0xffffffffffffffff:
        return ""
    return str(value)


def _float_or_blank(value, digits=6):
    """Sonlu ve negatif olmayan sayı; aksi halde boş."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if math.isnan(value) or math.isinf(value) or value < 0:
        return ""
    return ("%." + str(digits) + "f") % value


def _bool_or_blank(value):
    if value is True:
        return "1"
    if value is False:
        return "0"
    return ""


def enabled_from_env(environ=None):
    return _truthy((environ or os.environ).get("SDN_DATASET"))


class DatasetCollector(object):
    """PORT_METRICS -> CSV. Bkz. modül açıklaması."""

    def __init__(self, event_bus, path=DEFAULT_PATH, experiment_id=None,
                 label=UNKNOWN, declared_load_mbps=None,
                 max_bytes=DEFAULT_MAX_BYTES, logger=None,
                 clock=_utc_now, monotonic=None):
        import time
        self.bus = event_bus
        self.logger = logger or logging.getLogger(__name__)
        self.path = path
        self._clock = clock
        self._mono = monotonic or time.monotonic
        self.max_bytes = max_bytes
        self.experiment_id = (experiment_id or
                              "run-" + self._clock().strftime(
                                  "%Y%m%dT%H%M%SZ"))
        label = (label or UNKNOWN).strip().upper()
        if label not in LABELS:
            self.logger.warning("[DATASET] geçersiz etiket %r -> %s",
                                label, UNKNOWN)
            label = UNKNOWN
        self.label = label
        self.label_source = "operator_env" if label != UNKNOWN else "none"
        self.declared_load = _float_or_blank(declared_load_mbps)
        # Durum / sayaçlar (testlerde gözlenebilir)
        self.rows_written = 0
        self.rows_skipped_invalid = 0
        self.rows_skipped_duplicate = 0
        self.write_errors = 0
        self.disabled = False
        self._consecutive_errors = 0
        self._last = {}       # (dpid, port_no) -> (içerik anahtarı, mono t)
        self._isl = {}        # (dpid, port_no) -> True/False (LINK_UP/DOWN)
        self._file = None
        self._writer = None

        self._open()
        self.bus.subscribe(PORT_METRICS, self.on_port_metrics)
        self.bus.subscribe(LINK_UP, self.on_link_up)
        self.bus.subscribe(LINK_DOWN, self.on_link_down)
        self.logger.info("[DATASET] toplama AÇIK path=%s experiment=%s "
                         "label=%s", self.path, self.experiment_id,
                         self.label)

    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, event_bus, logger=None, environ=None):
        """SDN_DATASET açık değilse None döner (hiçbir şey kurulmaz)."""
        env = environ if environ is not None else os.environ
        if not enabled_from_env(env):
            return None
        try:
            max_mb = float(env.get("SDN_DATASET_MAX_MB") or 50)
        except ValueError:
            max_mb = 50
        load = env.get("SDN_DATASET_LOAD_MBPS")
        try:
            load = float(load) if load not in (None, "") else None
        except ValueError:
            load = None
        return cls(event_bus,
                   path=env.get("SDN_DATASET_PATH") or DEFAULT_PATH,
                   experiment_id=env.get("SDN_DATASET_EXPERIMENT") or None,
                   label=env.get("SDN_DATASET_LABEL") or UNKNOWN,
                   declared_load_mbps=load,
                   max_bytes=int(max_mb * 1024 * 1024), logger=logger)

    def close(self):
        self.bus.unsubscribe(PORT_METRICS, self.on_port_metrics)
        self.bus.unsubscribe(LINK_UP, self.on_link_up)
        self.bus.unsubscribe(LINK_DOWN, self.on_link_down)
        self._close_file()

    # ------------------------------------------------------------------
    # Dosya yönetimi
    # ------------------------------------------------------------------
    def _close_file(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = self._writer = None

    def _header_matches(self, path):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                return next(csv.reader(f), None) == list(COLUMNS)
        except (OSError, csv.Error):
            return False

    def _stamped_path(self):
        base, ext = os.path.splitext(self.path)
        return "%s.%s%s" % (base, self._clock().strftime("%Y%m%dT%H%M%SZ"),
                            ext or ".csv")

    def _open(self):
        """Dosyayı ekleme kipinde açar. Mevcut dosyanın başlığı farklıysa
        eski veriye dokunmadan zaman damgalı yeni dosyaya yazar."""
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            exists = os.path.exists(self.path) and \
                os.path.getsize(self.path) > 0
            if exists and not self._header_matches(self.path):
                new = self._stamped_path()
                self.logger.warning("[DATASET] %s başlığı uyuşmuyor; yeni "
                                    "dosya: %s", self.path, new)
                self.path, exists = new, False
            self._file = open(self.path, "a", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file, lineterminator="\n")
            if not exists:
                self._writer.writerow(COLUMNS)
                self._file.flush()
        except OSError:
            self.logger.exception("[DATASET] dosya açılamadı: %s", self.path)
            self._file = self._writer = None
            self.disabled = True

    def _rotate_if_needed(self):
        try:
            if self._file.tell() < self.max_bytes:
                return
        except (OSError, ValueError):
            return
        self._close_file()
        rotated = self._stamped_path()
        try:
            os.rename(self.path, rotated)
            self.logger.info("[DATASET] dosya döndürüldü -> %s", rotated)
        except OSError:
            self.logger.exception("[DATASET] döndürme başarısız")
        self._open()

    # ------------------------------------------------------------------
    # Link durumu (isl_port sütunu)
    # ------------------------------------------------------------------
    def _mark_link(self, link, state):
        try:
            self._isl[(link["src_dpid"], link["src_port"])] = state
            self._isl[(link["dst_dpid"], link["dst_port"])] = state
        except (KeyError, TypeError):
            pass

    def on_link_up(self, link):
        self._mark_link(link, True)

    def on_link_down(self, link):
        self._mark_link(link, False)

    # ------------------------------------------------------------------
    # PORT_METRICS
    # ------------------------------------------------------------------
    def build_row(self, m, now):
        """Payload'dan CSV satırı (liste) üretir; payload kullanılamazsa
        None. Ölçülmeyen alanlar boş kalır."""
        dpid, port = m.get("dpid"), m.get("port_no")
        if (isinstance(dpid, bool) or not isinstance(dpid, int) or dpid < 0
                or isinstance(port, bool) or not isinstance(port, int)
                or port < 0):
            return None
        values = {
            "timestamp_utc": _iso(now),
            "experiment_id": self.experiment_id,
            "label": self.label,
            "label_source": self.label_source,
            "dpid": str(dpid), "dpid_hex": "%016x" % dpid,
            "port_no": str(port),
            "port_name": m.get("name") if isinstance(m.get("name"), str)
            else "",
            "link_up": _bool_or_blank(m.get("link_up")),
            "admin_up": _bool_or_blank(m.get("admin_up")),
            "isl_port": _bool_or_blank(self._isl.get((dpid, port))),
            "interval_sec": _float_or_blank(m.get("interval_sec"), 3),
            # Ölçülmeyen alanlar: sahte değer yok
            "latency_ms": "", "e2e_loss_percent": "",
            "declared_load_mbps": self.declared_load,
        }
        for name in _COUNTERS:
            values[name] = _int_or_blank(m.get(name))
        for column, key in _RATES:
            values[column] = _float_or_blank(m.get(key))
        return [values[c] for c in COLUMNS]

    def on_port_metrics(self, m):
        if self.disabled or self._writer is None:
            return
        try:
            self._record(m)
        except Exception:
            self._note_error()
            self.logger.exception("[DATASET] kayıt hatası")

    def _record(self, m):
        now = self._clock()
        row = self.build_row(m, now)
        if row is None:
            self.rows_skipped_invalid += 1
            return
        # Kopya koruması: zaman ve etiket dışındaki içerik aynı VE çok kısa
        # süre içinde geldiyse aynı olayın tekrar teslimi sayılır.
        key = (m["dpid"], m["port_no"])
        content = tuple(row[4:])
        mono = self._mono()
        last = self._last.get(key)
        if last and last[0] == content and mono - last[1] < DEDUP_WINDOW_SEC:
            self.rows_skipped_duplicate += 1
            return
        self._last[key] = (content, mono)

        self._rotate_if_needed()
        if self._writer is None:
            return
        try:
            self._writer.writerow(row)
            self._file.flush()
        except OSError:
            self._note_error()
            self.logger.exception("[DATASET] yazma hatası")
            return
        self._consecutive_errors = 0
        self.rows_written += 1

    def _note_error(self):
        self.write_errors += 1
        self._consecutive_errors += 1
        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self.disabled = True
            self._close_file()
            self.logger.error("[DATASET] art arda %d hata; toplama "
                              "kapatıldı (controller etkilenmez)",
                              self._consecutive_errors)
