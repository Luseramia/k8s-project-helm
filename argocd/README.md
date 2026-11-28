# argocd/ — ingress + bootstrap notes

โฟลเดอร์นี้มีแค่ ingress ของ ArgoCD (`ingress.yaml`) ซึ่งถูก sync โดย Application
`argocd-ingress` (source path `argocd`, branch `main`)

- host: `argocd.tarchunk.win`
- class: `nginx` → LoadBalancer `192.168.1.101`
- TLS: cert-manager `ClusterIssuer/letsencrypt-dns01` ออกใบให้ secret `argocd-ingress-tls`
  (ต่ออายุอัตโนมัติ; ใบปัจจุบันหมดอายุ 30 ม.ค. 2027)
- backend: `argocd-server:80` แบบ **HTTP** (`backend-protocol: HTTP`) — TLS ถูก terminate ที่ ingress

## Bootstrap settings ที่ *ไม่ได้* อยู่ใน git

หลังติดตั้ง ArgoCD จาก manifest upstream ต้องตั้ง 2 ค่านี้ด้วยมือ (ครั้งเดียวต่อคลัสเตอร์):

```bash
kubectl -n argocd patch cm argocd-cmd-params-cm --type=merge \
  -p='{"data":{"server.insecure":"true"}}'

kubectl -n argocd patch cm argocd-cm --type=merge \
  -p='{"data":{"url":"https://argocd.tarchunk.win"}}'

kubectl -n argocd rollout restart deploy/argocd-server
```

- `server.insecure: "true"` — deployment wire ค่านี้ผ่าน env `ARGOCD_SERVER_INSECURE` อยู่แล้ว
  จึงไม่ต้องเติม arg `--insecure` (ถ้าเติม arg ตรง ๆ แล้วมีคน apply manifest upstream ทับ flag จะหลุด)
- `url` — ใช้สร้าง redirect / OIDC callback ให้ตรงโดเมนจริง

### ถ้าไม่ตั้งจะเกิดอะไร

`argocd-server` จะเสิร์ฟ **TLS ของตัวเองบนพอร์ต 8080** และตอบ `307` redirect HTTP → HTTPS
แต่ ingress ส่ง HTTP เข้าไป (เพราะ terminate TLS แล้ว) ผลคือ redirect วนไม่จบ:

```
https://argocd.tarchunk.win/applications → 307 → https://argocd.tarchunk.win/applications → ...
```

### ทำไมไม่เก็บ 2 ค่านี้เป็น manifest ในโฟลเดอร์นี้

`argocd-cmd-params-cm` และ `argocd-cm` ถูกสร้างโดย manifest upstream ของ ArgoCD ซึ่งมี key
อีกหลายสิบตัว ถ้าใส่ไฟล์ที่มีแค่ key เดียวไว้ใน path `argocd` ตอน sync ArgoCD จะมอง key
ที่เหลือว่าเป็นส่วนเกินและรายงาน `OutOfSync` ค้าง จึงเลือกเก็บเป็นขั้นตอน bootstrap
พร้อม note นี้แทน (ต้องเขียนกำกับใน README เสมอเมื่อติดตั้งใหม่)

## ตรวจสอบว่า HTTPS ใช้งานได้

```bash
R="--resolve argocd.tarchunk.win:443:192.168.1.101"

# TLS + cert
echo | openssl s_client -connect 192.168.1.101:443 -servername argocd.tarchunk.win 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates

# ต้องได้ 308 ไป https
curl -sS -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
  -H 'Host: argocd.tarchunk.win' http://192.168.1.101/

# SPA ต้องได้ 200 (ต้องส่ง Accept: text/html ไม่งั้นได้ 404 ซึ่งเป็นพฤติกรรมปกติของ SPA)
for p in / /applications /login; do
  curl -sS -o /dev/null -H 'Accept: text/html' \
    -w "$p -> %{http_code}\n" $R https://argocd.tarchunk.win$p
done

# API
curl -sS $R https://argocd.tarchunk.win/api/version
curl -sS -o /dev/null -w '%{http_code}\n' $R https://argocd.tarchunk.win/api/v1/applications  # 401 = ปกติ
```
