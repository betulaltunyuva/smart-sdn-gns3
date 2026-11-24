"""
Smart SDN (GNS3) - Aşama 9.3: güvenli etiketleme

Etiket, ölçülen değerlerden TÜRETİLMEZ. Etiketi yalnızca operatörün
doğruladığı deney senaryosu belirler. Bu modül iki iş yapar:

  1) Etiket sabitleri ve kuralları (collector tarafından da kullanılır).
  2) Ham CSV'ye, "anotasyon" dosyasındaki doğrulanmış zaman aralıklarına
     göre etiket uygulayan çevrimdışı araç. Ham dosya değiştirilmez;
     etiketli kopya yeni dosyaya yazılır. Aralık dışında kalan veya
     çelişen satırlar UNKNOWN olur.

Anotasyon CSV sütunları:
    experiment_id, start_utc, end_utc, label, evidence_type, evidence_note
  start_utc/end_utc: ISO-8601 UTC (ör. 2026-11-23T10:00:00Z); [start, end).

Her etiketin kabul ettiği KANIT türleri kısıtlıdır (EVIDENCE_RULES). Sıfır
trafik ("zero_traffic") ya da LLDP link kaybı ("lldp_loss") hiçbir etiket
için kanıt sayılmaz; FAILURE için fiziksel/idari arızanın bilerek
uygulandığı doğrulanmalıdır.

Kullanım:
    python3 -m utils.dataset_labels HAM.csv ANOTASYON.csv -o ETIKETLI.csv
"""

import argparse
import csv
import datetime
import os
import sys

NORMAL = "NORMAL"
LOAD = "LOAD"
CONGESTION = "CONGESTION"
FAILURE = "FAILURE"
UNKNOWN = "UNKNOWN"
LABELS = (NORMAL, LOAD, CONGESTION, FAILURE, UNKNOWN)

# Etiket -> kabul edilen kanıt türleri
EVIDENCE_RULES = {
    # Hata enjekte edilmedi, yük üretilmedi; yalnızca arka plan trafiği
    NORMAL: ("baseline_no_fault",),
    # Bilinen/ayarlı bir trafik üreteci çalıştırıldı (örn. iperf -b X)
    LOAD: ("traffic_generator",),
    # Tıkanıklık ayrı bir ölçümle doğrulandı: uçtan uca kayıp, gecikme
    # artışı veya kuyruk/drop sayaçları (yalnızca yüksek Mbps yetmez)
    CONGESTION: ("e2e_loss", "latency_increase", "drop_counters"),
    # Arıza bilerek ve doğrulanarak uygulandı
    FAILURE: ("physical_link_down", "port_admin_down", "node_stopped"),
}
# Hiçbir etiket için GEÇERLİ olmayan, sık karıştırılan "kanıtlar"
REJECTED_EVIDENCE = ("zero_traffic", "lldp_loss", "link_removed_event")

ANNOTATION_COLUMNS = ("experiment_id", "start_utc", "end_utc", "label",
                      "evidence_type", "evidence_note")


def parse_utc(text):
    """ISO-8601 (Z veya +00:00 / ofsetli) -> aware UTC datetime."""
    text = (text or "").strip()
    if not text:
        raise ValueError("boş zaman damgası")
    dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("zaman dilimi yok (UTC 'Z' gerekli): %r" % text)
    return dt.astimezone(datetime.timezone.utc)


def validate_annotation(a):
    """Geçerli anotasyonu (zaman nesneleriyle) döner; kural ihlalinde
    ValueError fırlatır."""
    label = (a.get("label") or "").strip().upper()
    ev = (a.get("evidence_type") or "").strip().lower()
    if not (a.get("experiment_id") or "").strip():
        raise ValueError("experiment_id boş")
    if label == UNKNOWN or label not in EVIDENCE_RULES:
        raise ValueError("anotasyon etiketi şunlardan biri olmalı: %s "
                         "(UNKNOWN anotasyonla verilmez)"
                         % ", ".join(EVIDENCE_RULES))
    if ev in REJECTED_EVIDENCE:
        raise ValueError("%r kanıt olarak kabul edilmez" % ev)
    if ev not in EVIDENCE_RULES[label]:
        raise ValueError("%s için kanıt türü %s olmalı, %r verildi"
                         % (label, "/".join(EVIDENCE_RULES[label]), ev))
    if not (a.get("evidence_note") or "").strip():
        raise ValueError("evidence_note zorunlu (nasıl doğrulandı?)")
    start, end = parse_utc(a.get("start_utc")), parse_utc(a.get("end_utc"))
    if end <= start:
        raise ValueError("end_utc, start_utc'den sonra olmalı")
    return {"experiment_id": a["experiment_id"].strip(), "label": label,
            "start": start, "end": end,
            "source": "annotation:%s" % ev}


def load_annotations(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ANNOTATION_COLUMNS
                   if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("anotasyon sütunları eksik: %s" % missing)
        out = []
        for n, row in enumerate(reader, start=2):
            try:
                out.append(validate_annotation(row))
            except ValueError as e:
                raise ValueError("%s satır %d: %s" % (path, n, e))
    return out


def label_for(experiment_id, ts, annotations):
    """(etiket, kaynak). Eşleşme yoksa veya aralıklar çelişiyorsa UNKNOWN."""
    hits = [a for a in annotations
            if a["experiment_id"] == experiment_id
            and a["start"] <= ts < a["end"]]
    labels = set(a["label"] for a in hits)
    if len(labels) == 1:
        return hits[0]["label"], hits[0]["source"]
    return UNKNOWN, ("conflict" if labels else "none")


def apply_annotations(raw_path, annotation_path, out_path):
    """Ham CSV'yi okuyup etiketli kopyayı yazar. Ham dosyaya dokunmaz.
    {"rows", "labeled", "unknown", "conflict", "bad_rows"} sayaçlarını
    döner."""
    if os.path.abspath(raw_path) == os.path.abspath(out_path):
        raise ValueError("çıktı dosyası ham dosyayla aynı olamaz")
    if os.path.exists(out_path):
        raise ValueError("çıktı zaten var, üzerine yazılmaz: %s" % out_path)
    annotations = load_annotations(annotation_path)
    stats = {"rows": 0, "labeled": 0, "unknown": 0, "conflict": 0,
             "bad_rows": 0}
    with open(raw_path, newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        fields = reader.fieldnames or []
        for needed in ("timestamp_utc", "experiment_id", "label",
                       "label_source"):
            if needed not in fields:
                raise ValueError("ham CSV'de '%s' sütunu yok" % needed)
        with open(out_path, "w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=fields,
                                    lineterminator="\n")
            writer.writeheader()
            for row in reader:
                stats["rows"] += 1
                try:
                    ts = parse_utc(row["timestamp_utc"])
                except (ValueError, TypeError):
                    stats["bad_rows"] += 1
                    row["label"], row["label_source"] = UNKNOWN, "none"
                    writer.writerow(row)
                    continue
                label, source = label_for(row["experiment_id"], ts,
                                          annotations)
                row["label"], row["label_source"] = label, source
                if label == UNKNOWN:
                    stats["unknown"] += 1
                    stats["conflict"] += source == "conflict"
                else:
                    stats["labeled"] += 1
                writer.writerow(row)
    return stats


def main(argv=None):
    p = argparse.ArgumentParser(description="Ham port CSV'sini doğrulanmış "
                                "anotasyonlarla etiketler.")
    p.add_argument("raw_csv")
    p.add_argument("annotations_csv")
    p.add_argument("-o", "--output", required=True)
    a = p.parse_args(argv)
    try:
        stats = apply_annotations(a.raw_csv, a.annotations_csv, a.output)
    except (ValueError, OSError) as e:
        print("HATA: %s" % e, file=sys.stderr)
        return 1
    print("satır=%(rows)d etiketli=%(labeled)d UNKNOWN=%(unknown)d "
          "(çelişen=%(conflict)d, bozuk zaman=%(bad_rows)d)" % stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
