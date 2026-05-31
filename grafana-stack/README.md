# LGTM Stack via ArgoCD (GitOps)

Deploy observability stack ผ่าน ArgoCD แบบ App of Apps pattern
เปลี่ยน YAML ใน git → ArgoCD sync อัตโนมัติ → drift detection + rollback ฟรี

## โครงสร้าง

```
.
├── argocd/
│   ├── root.yaml                ← App of Apps root
│   └── apps/                    ← apps ย่อย (sync wave จัดลำดับ)
├── helm-values/                 ← Helm values
└── manifests/                   ← Raw k8s manifests
```

## Sync waves (ลำดับการ deploy)

ArgoCD ติดตั้งตาม `argocd.argoproj.io/sync-wave` annotation:

```
Wave 0:  monitoring-base       (namespace + external-secrets configs)
Wave 1:  kube-prometheus-stack (Prometheus operator + CRDs)
Wave 2:  loki, tempo           (รอ namespace + CRDs)
Wave 3:  alloy                 (รอ loki gateway)
Wave 4:  monitoring-extras     (ServiceMonitors — รอ Prometheus CRDs)
```

## Pre-requisites

1. **ArgoCD ติดตั้งแล้ว** ใน cluster ✓ (คุณมีอยู่แล้ว)

2. **Git repo** — push folder นี้ขึ้น git (GitHub/GitLab/Gitea) ได้ทั้ง public และ private
   - ถ้า private ต้องตั้ง repo credentials ใน ArgoCD ก่อน

3. **External Secrets Operator (ESO)** (แนะนำ) — สำหรับดึง secrets จาก Vault
   ```bash
   helm repo add external-secrets https://charts.external-secrets.io
   helm install external-secrets external-secrets/external-secrets \
     -n external-secrets-system --create-namespace
   ```
   หรือเพิ่มเข้าไปเป็น ArgoCD Application อีกตัว

4. **Vault setup** — สร้าง KV path เก็บ S3 credentials:
   ```bash
   vault kv put secret/observability/seaweedfs \
     access_key=YOUR_ACCESS_KEY \
     secret_key=YOUR_SECRET_KEY
   ```

5. **StorageClass** ใน cluster พร้อม

## Bootstrap (รัน 1 ครั้ง)

```bash
# 1. แก้ argocd/root.yaml ให้ชี้ไป git repo ของคุณ
vim argocd/root.yaml
# แก้ spec.source.repoURL: https://github.com/YOU/lgtm-gitops.git

# 2. แก้ helm-values + manifests ตามต้องการ (S3 endpoint, domain, storageClass)

# 3. commit + push ขึ้น git
git add .
git commit -m "initial LGTM stack"
git push

# 4. Apply root app — เป็นการ bootstrap ครั้งเดียวเท่านั้น
kubectl apply -f argocd/root.yaml

# จากนั้น ArgoCD จะ:
#  → สร้าง Applications ลูกทั้งหมดเอง
#  → ติดตั้งตามลำดับ sync wave
#  → ดู status ที่ UI ArgoCD
```

## ดู status

```bash
# ผ่าน UI
kubectl port-forward -n argocd svc/argocd-server 8080:443
# → https://localhost:8080

# ผ่าน CLI
argocd app list
argocd app get lgtm-root
argocd app get kube-prometheus-stack
argocd app sync kube-prometheus-stack   # force sync
```

## Workflow ปกติ (หลัง bootstrap)

```bash
# แก้ values ของ Loki (เช่นเพิ่ม retention)
vim helm-values/loki.yaml

# commit + push
git commit -am "extend loki retention to 60d"
git push

# ArgoCD auto-sync ภายใน 3 นาที (default polling)
# หรือ force sync ทันที:
argocd app sync loki
```

## Rollback

```bash
# ดู history
argocd app history loki

# rollback ไป revision เก่า
argocd app rollback loki 3
```

หรือ revert commit ใน git แล้ว push — ArgoCD จะ sync กลับเอง

## Auto-sync vs Manual sync

ใน Application manifest:
```yaml
syncPolicy:
  automated:
    prune: true       # ลบ resource ที่หายไปจาก git
    selfHeal: true    # กลับคืนค่าถ้ามีคน manual แก้ใน cluster
```

ถ้าอยาก review ก่อน sync ทุกครั้ง ลบ block `automated` ออก
แล้วใช้ `argocd app sync xxx` เอง

## Troubleshooting

**App stuck ที่ "OutOfSync"**
```bash
argocd app diff kube-prometheus-stack
```

**CRD ติดตั้งไม่ผ่าน** — บางที kube-prometheus-stack CRDs ใหญ่เกิน annotation limit
ใช้ Server-Side Apply (ตั้งใน manifest แล้ว):
```yaml
syncOptions:
  - ServerSideApply=true
```

**Secrets ไม่ขึ้น** — เช็ค ExternalSecret status:
```bash
kubectl get externalsecret -n monitoring
kubectl describe externalsecret loki-s3-credentials -n monitoring
```

## ทำไม External Secrets ดีกว่า commit secret ใน git

- **ปลอดภัย** — credentials ไม่อยู่ใน git history
- **Rotation อัตโนมัติ** — เปลี่ยน secret ที่ Vault → ESO refresh ให้
- **Single source of truth** — Vault เป็นที่เก็บ secret กลาง
- **Audit** — Vault มี audit log ครบ
