#!/bin/bash
# install.sh - ติดตั้ง LGTM stack ทั้งหมดใน 1 ครั้ง
#
# Pre-requisites:
#   1. แก้ secrets.yaml ใส่ credentials ของ SeaweedFS
#   2. แก้ storageClassName ในทุก values file
#   3. แก้ S3 endpoint URL ใน loki-values.yaml + tempo-values.yaml
#   4. แก้ domain ของ Grafana ingress

set -euo pipefail

# สี ๆ
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}▶${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }

# ─────────────────────────────────────────────────────
# 1. เพิ่ม helm repos
# ─────────────────────────────────────────────────────
log "Adding helm repos..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
helm repo update

# ─────────────────────────────────────────────────────
# 2. สร้าง namespace + secrets
# ─────────────────────────────────────────────────────
log "Creating namespace and secrets..."

# เช็คก่อนว่าแก้ secrets แล้ว
if grep -q "YOUR_SEAWEEDFS_ACCESS_KEY" secrets.yaml; then
  warn "secrets.yaml ยังไม่ได้แก้! กรุณาใส่ SeaweedFS credentials จริงก่อน"
  exit 1
fi

kubectl apply -f secrets.yaml

# ─────────────────────────────────────────────────────
# 3. ติดตั้ง kube-prometheus-stack
# ─────────────────────────────────────────────────────
log "Installing kube-prometheus-stack (Prometheus + Grafana + Alertmanager)..."
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values kube-prometheus-stack-values.yaml \
  --wait \
  --timeout 10m

# ─────────────────────────────────────────────────────
# 4. ติดตั้ง Loki
# ─────────────────────────────────────────────────────
log "Installing Loki..."
helm upgrade --install loki grafana/loki \
  --namespace monitoring \
  --values loki-values.yaml \
  --wait \
  --timeout 10m

# ─────────────────────────────────────────────────────
# 5. ติดตั้ง Tempo
# ─────────────────────────────────────────────────────
log "Installing Tempo..."
helm upgrade --install tempo grafana/tempo \
  --namespace monitoring \
  --values tempo-values.yaml \
  --wait \
  --timeout 10m

# ─────────────────────────────────────────────────────
# 6. ติดตั้ง Alloy (log collector)
# ─────────────────────────────────────────────────────
log "Installing Grafana Alloy (log collector)..."
helm upgrade --install alloy grafana/alloy \
  --namespace monitoring \
  --values alloy-values.yaml \
  --wait \
  --timeout 5m

# ─────────────────────────────────────────────────────
# 7. ServiceMonitors สำหรับ apps
# ─────────────────────────────────────────────────────
log "Applying ServiceMonitors for existing apps..."
kubectl apply -f servicemonitors.yaml

# ─────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────
echo ""
log "Installation complete! 🎉"
echo ""
echo "ตรวจสอบ pods:"
echo "  kubectl get pods -n monitoring"
echo ""
echo "ดู Grafana admin password:"
echo "  kubectl get secret -n monitoring kps-grafana -o jsonpath='{.data.admin-password}' | base64 -d ; echo"
echo ""
echo "Access Grafana:"
echo "  - ผ่าน ingress:  http://grafana.lan  (ตั้ง DNS หรือ /etc/hosts)"
echo "  - หรือ port-forward:"
echo "    kubectl port-forward -n monitoring svc/kps-grafana 3000:80"
echo ""
echo "ตรวจสอบ S3 buckets ใน SeaweedFS:"
echo "  - loki-chunks, loki-ruler, loki-admin (auto-created โดย Loki)"
echo "  - tempo-traces (auto-created โดย Tempo)"
