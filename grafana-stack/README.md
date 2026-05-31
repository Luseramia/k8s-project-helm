# LGTM Stack on K8s (Grafana ครบสูตร)

ชุด Helm values + manifest สำหรับติดตั้ง observability stack เต็มรูปแบบ:

- **Prometheus** (kube-prometheus-stack) — metrics
- **Loki** — logs (S3 backend → SeaweedFS)
- **Tempo** — traces (S3 backend → SeaweedFS)
- **Grafana** — UI ตัวเดียวดูทุกอย่าง
- **Alertmanager** — alerts
- **Grafana Alloy** — log collector (DaemonSet) แทน Promtail (Promtail deprecated แล้ว)
- **node-exporter + kube-state-metrics** — มากับ kube-prometheus-stack

## Prerequisites

ก่อนรันต้องเตรียม:

1. **StorageClass** ที่ใช้งานได้ — แนะนำ NFS จาก TrueNAS หรือ longhorn
   - เปลี่ยน `storageClassName` ในทุก values file ตามของจริง
   - ดู: `kubectl get storageclass`

2. **SeaweedFS S3 credentials**
   - endpoint URL (เช่น `http://seaweedfs.truenas.lan:8333`)
   - access key + secret key
   - สร้าง bucket 3 ตัวล่วงหน้า: `loki-chunks`, `loki-ruler`, `tempo-traces`
   - หรือเปิด auto-create bucket ใน SeaweedFS

3. **Ingress controller** — ของคุณคือ nginx-ingress ที่ใช้อยู่แล้ว ✓

4. **DNS** หรือ /etc/hosts ชี้ `grafana.lan` → ingress IP

## ลำดับการติดตั้ง

```bash
# 1. แก้ secrets.yaml ใส่ค่า SeaweedFS credentials ของคุณ
vim secrets.yaml

# 2. แก้ storageClassName ในแต่ละ values file ให้ตรงกับของคุณ
grep -r storageClassName .

# 3. แก้ domain ของ Grafana ingress (default: grafana.lan)
vim kube-prometheus-stack-values.yaml

# 4. รัน
./install.sh
```

## หลังติดตั้ง

```bash
# ดู pod ทั้งหมด
kubectl get pods -n monitoring

# ดู Grafana admin password (ถ้าไม่ได้เปลี่ยน)
kubectl get secret -n monitoring kps-grafana \
  -o jsonpath="{.data.admin-password}" | base64 -d ; echo

# Port-forward Grafana ถ้ายังไม่ได้ตั้ง ingress
kubectl port-forward -n monitoring svc/kps-grafana 3000:80
# → http://localhost:3000  (admin / <password>)
```

Datasources (Prometheus, Loki, Tempo) ถูกตั้งค่ามาในตัว Grafana แล้ว
Dashboards พื้นฐานของ k8s + node-exporter มาด้วยเลย

## Resource footprint (รวมทั้ง stack)

```
Prometheus:        ~3 GB RAM, ~30 GB storage (7d retention)
Loki:              ~1.5 GB RAM, ~10 GB storage (hot)
Tempo:             ~1 GB RAM, ~10 GB storage (hot)
Grafana:           ~300 MB RAM, 5 GB storage
Alertmanager:      ~200 MB RAM, 5 GB storage
Alloy (DaemonSet): ~200 MB RAM per node
node-exporter:     ~50 MB RAM per node
kube-state:        ~200 MB RAM
────────────────────────────────────────
รวม:              ~7 GB RAM ใน worker observability + ~250 MB ต่อ worker อื่นๆ
```

Cold data ทั้งหมดอยู่ใน SeaweedFS — Loki/Tempo offload อัตโนมัติ

## Customization สำคัญ

### เพิ่ม retention metrics ยาวขึ้น
ใน `kube-prometheus-stack-values.yaml`:
```yaml
prometheus:
  prometheusSpec:
    retention: 30d         # เพิ่มจาก 7d
    retentionSize: 80GiB   # เพิ่ม storage ด้วย
```
(แต่ถ้าจะเก็บยาวจริงๆ แนะนำเพิ่ม Thanos sidecar → S3 ดีกว่า)

### เปลี่ยน Grafana password
```yaml
grafana:
  adminPassword: "your-secure-password"
```

### เพิ่ม ingress hostname
```yaml
grafana:
  ingress:
    hosts:
      - grafana.yourdomain.com
```

## Troubleshooting

**Loki/Tempo connect S3 ไม่ได้** — check:
- SeaweedFS S3 endpoint เข้าถึงได้จาก pod (`kubectl exec ... -- curl`)
- ค่าใน secret ถูกต้อง
- bucket มีอยู่จริง

**Prometheus ไม่ scrape app** — check:
- ServiceMonitor มี label ตรงกับ `serviceMonitorSelector`
- Service มี port name ตรงกับ ServiceMonitor

**Grafana login ไม่ผ่าน** — get password ใหม่:
```bash
kubectl get secret -n monitoring kps-grafana \
  -o jsonpath="{.data.admin-password}" | base64 -d
```
