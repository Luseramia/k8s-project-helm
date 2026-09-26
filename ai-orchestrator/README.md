# ai-orchestrator

Plain Kubernetes manifests, following the backend services in this repository. Application source, Dockerfile, and Jenkinsfile live in https://github.com/Luseramia/ai-orchestrator.

## Runtime

- Namespace: `codex`; one replica.
- API: `http://ai-orchestrator.codex.svc.cluster.local:8000` (`GET /health`, `POST /generate`, `POST /financial-statements/normalize`).
- Image: `registry.registry.svc.cluster.local:5000/ai-orchestrator:<Jenkins build number>`.
- Codex: `http://codex-gateway.codex.svc.cluster.local:8080` over HTTP.
- Credential: the existing `codex-gateway-auth` Secret, key `token`, in `codex`.

The Pod's `app.kubernetes.io/name: ai-orchestrator` label and `codex` namespace match the gateway chart's default NetworkPolicy. The Secret is shared with the gateway in the same namespace. `secretKeyRef` provides the decoded token automatically; do not paste a Base64 token into the ConfigMap or commit a Secret manifest.

The container runs as UID/GID 10001 with a read-only root filesystem and writable `/tmp`. The service is internal ClusterIP. No database, PVC, or Codex CLI installation is needed for this HTTP transport.

## First deployment

1. Commit and push the new files in both repositories to `main`. The application commit must include `app/chains/codex_adapter.py`, `tests/`, `scripts/update-deployment-image.sh`, `requirements.txt`, `Dockerfile`, `.dockerignore`, and `Jenkinsfile`.
2. Create a Jenkins Pipeline job using SCM `https://github.com/Luseramia/ai-orchestrator.git`, branch `main`, script path `Jenkinsfile`, or paste that Jenkinsfile into an inline Pipeline. It requires the Kubernetes plugin, the existing `kaniko` service account/Vault setup, and SSH credential `github_key` with read access to the application repository and write access to this deployment repository. Checkout uses GitHub SSH over port 443, matching the existing Codex pipeline. Nodes use the same HTTP registry configuration as the existing workloads.
3. Run the Jenkins job. It checks out both repositories under `/ci-workspace`, runs the adapter tests and API health smoke check, builds and pushes the image with Kaniko, then commits the image tag to this directory's `deployment.yaml`. Argo CD automatically syncs later builds; an Argo API token is not required.
4. In an authenticated cluster terminal, check the existing Secret without displaying its value and register the Argo CD application once:

   ```bash
   kubectl -n codex get secret codex-gateway-auth
   # Run from an up-to-date checkout of k8s-project-helm.
   kubectl apply -f ai-orchestrator/argocd-app.yaml
   ```

5. Wait for Argo CD to sync, then verify the rollout and gateway connection:

   ```bash
   kubectl -n codex rollout status deployment/ai-orchestrator --timeout=5m
   kubectl -n codex get pods -l app=ai-orchestrator
   kubectl -n codex exec deployment/ai-orchestrator -- python -c 'import httpx; r=httpx.get("http://127.0.0.1:8000/health", trust_env=False); r.raise_for_status(); print(r.json())'
   kubectl -n codex exec deployment/ai-orchestrator -- python -c 'import httpx; r=httpx.get("http://codex-gateway.codex.svc.cluster.local:8080/ready", timeout=10, trust_env=False); r.raise_for_status(); print(r.json())'
   ```

The gateway readiness request verifies cluster DNS and the NetworkPolicy path without generating a model response. To verify authentication and model execution as well, this optional one-shot command consumes a small amount of Codex quota and prints only the model's reply:

```bash
kubectl -n codex exec deployment/ai-orchestrator -- python -c 'import asyncio; from app.chains.codex_adapter import call_codex; print(asyncio.run(call_codex("Reply with exactly: ai-orchestrator connected")))'
```

Configure the backend/n8n caller to POST to `http://ai-orchestrator.codex.svc.cluster.local:8000/generate` with the documented application request body. Allow at least 1300 seconds for generation plus a possible JSON repair. Probes call the local API only (readiness every 15 seconds, liveness every 30 seconds); they do not invoke Codex. A healthy API does not by itself prove the remote model is available.

The financial-statement endpoint uses the same internal ClusterIP and gateway
credential. Callers do not need the gateway token. A backend running outside the
cluster can port-forward this Service to `127.0.0.1:18000` and set
`AI_ORCHESTRATOR_REST_URL=http://127.0.0.1:18000`.

## Changes and rollback

Jenkins updates the image only after tests and the image push succeed. Argo CD owns the application Deployment, Service, ConfigMap, and ServiceAccount; `argocd-app.yaml` is excluded from the application source so the application does not manage itself. The existing Codex Secret and workloads are not part of this application's resource set.

Revert the image-tag commit in Git to roll back; Argo CD self-heal would undo an out-of-band `kubectl set image` change. Configuration and Secret values are read at Pod startup. After changing those values without a new image, restart only this Deployment with `kubectl -n codex rollout restart deployment/ai-orchestrator`.

The 1320-second termination grace period lets an in-flight request finish during a rollout, including up to two 630-second Codex calls. The gateway currently accepts one generation at a time; concurrent calls may receive a busy error. Deploying more API replicas does not increase gateway concurrency.

To use a different namespace, change all manifest namespaces and the Argo destination, provision the gateway token Secret there, and set `gateway.networkPolicy.allowedNamespace` in the Codex chart accordingly. If that gateway setting is already overridden, reconcile it with `codex` before deploying these defaults.
