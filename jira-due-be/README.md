# jira-due-be — NestJS API ของ Jira Due Dashboard

ซอร์สโค้ด + Dockerfile: `personal_project/jiraissue/jira-due-dashboard/jira-due-dashboard/backend/`

- port 3000, route ทั้งหมดอยู่ใต้ `/api`
- DB: **Postgres ตัวเดิมนอก cluster** `192.168.1.44:5432` (db `jira_issues`, user `tarchunk`
  — ตัวเดียวกับที่ n8n upsert) config อยู่ใน `configmap.yaml` รหัสผ่านมาจาก secret
- ไม่มี ingress — frontend (`jira-due-fe`) proxy `/api` เข้ามาที่ service
  `jira-due-backend.jira-due.svc.cluster.local:3000` ใน cluster เอง

## Setup ครั้งแรก

```bash
# secret รหัสผ่าน DB — ไม่ commit ลง git
kubectl create namespace jira-due
kubectl create secret generic jira-due-secrets -n jira-due \
  --from-literal=DB_PASSWORD='<รหัสผ่านของ user tarchunk>'

# build + push image (รันจากโฟลเดอร์ backend/ ของโปรเจกต์)
TAG=1
docker build -t registry.registry.svc.cluster.local:5000/jira-due-backend:$TAG .
docker push registry.registry.svc.cluster.local:5000/jira-due-backend:$TAG

# commit ขึ้น git แล้วสร้าง ArgoCD Application
kubectl apply -f argocd-app.yaml
```

ออก version ใหม่: build/push tag ใหม่ → แก้เลข tag ใน `deployment.yaml` → commit → ArgoCD sync เอง

> - Postgres ที่ 192.168.1.44 ต้องรับ connection จาก IP ของ pod/node ใน cluster
>   (เช็ค `pg_hba.conf` / `listen_addresses` ถ้าต่อไม่ติด)
> - readinessProbe ยิง `/api/issues/summary` ซึ่ง query DB จริง — pod ไม่ ready = ดู log เรื่อง DB ก่อน
