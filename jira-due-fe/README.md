# jira-due-fe — Angular dashboard ของ Jira Due Dashboard

ซอร์สโค้ด + Dockerfile: `personal_project/jiraissue/jira-due-dashboard/jira-due-dashboard/frontend/`

- nginx เสิร์ฟ static Angular (port 80) + proxy `/api` →
  `jira-due-backend.jira-due.svc.cluster.local:3000` ([jira-due-be](../jira-due-be/))
  → ใช้โดเมนเดียว ไม่ติด CORS
- ingress: `https://jira-due.tarchunk.win` (nginx + cert-manager `letsencrypt-dns01`)

## Setup ครั้งแรก

deploy `jira-due-be` ก่อน (namespace + secret อยู่ฝั่งนั้น) แล้ว:

```bash
# build + push image (รันจากโฟลเดอร์ frontend/ ของโปรเจกต์)
TAG=1
docker build -t registry.registry.svc.cluster.local:5000/jira-due-frontend:$TAG .
docker push registry.registry.svc.cluster.local:5000/jira-due-frontend:$TAG

# commit ขึ้น git แล้วสร้าง ArgoCD Application
kubectl apply -f argocd-app.yaml
```

ออก version ใหม่: build/push tag ใหม่ → แก้เลข tag ใน `deployment.yaml` → commit → ArgoCD sync เอง

## เช็คผล

```bash
curl -k https://jira-due.tarchunk.win/api/issues/summary   # ผ่าน proxy → backend
```

เปิด https://jira-due.tarchunk.win (DNS ต้องชี้ host นี้เข้า ingress เหมือนโดเมนอื่น)
