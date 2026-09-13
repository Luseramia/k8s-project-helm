# Codex Workspace Helm Chart — ChatGPT Login Edition

A persistent Kubernetes coding workspace with OpenAI Codex CLI that signs in with your ChatGPT account. This chart does **not** require an `OPENAI_API_KEY`.

Codex is available through ChatGPT plans, with usage limits depending on the plan. When you sign in to Codex with ChatGPT, usage follows your ChatGPT plan rather than API-key billing.

## 1. Build the image

```bash
docker build -t ghcr.io/YOUR_ORG/codex-workspace:3 .
docker push ghcr.io/YOUR_ORG/codex-workspace:3
```

Change `image.repository` in `values.yaml` to match your registry. The Dockerfile defaults to the published, pinned Codex CLI version `0.154.0`, so builds work without extra CI arguments. To preserve a different version verified in your existing Pod, add `--build-arg "CODEX_VERSION=<verified-cli-version>"`. The chart's image tag and the Codex CLI version are separate values.

### Jenkins / Kaniko builds

The existing pipeline can use the Dockerfile's pinned default without supplying `CODEX_VERSION`. Setting a Jenkins environment variable or Helm value alone does not override a Dockerfile `ARG`. To inspect the existing Pod's version, run `kubectl -n codex exec <pod-name> -c codex -- codex --version` and use only the version number from the output.

Run this inside the Kaniko container from the `codex-workspace` directory, with `PUSH_IMAGE` set to the destination registry/repository:tag:

```bash
: "${PUSH_IMAGE:?Set PUSH_IMAGE to the complete registry/repository:tag}"
/kaniko/executor \
  --context "$PWD" \
  --dockerfile "$PWD/Dockerfile" \
  --destination "$PUSH_IMAGE"
```

To override the default, set `CODEX_VERSION` to the desired exact version and add `--build-arg "CODEX_VERSION=$CODEX_VERSION"` to the Kaniko command. Do not pass that flag with an empty value: an explicit empty value overrides the Dockerfile default. Omit the flag when no override is needed.

If an older build exits with status 1 immediately after successful package installation and before npm output, a missing/empty `CODEX_VERSION` is a likely cause: the old Dockerfile used silent `test` commands after installing packages and had no default. The current Dockerfile supplies a pinned default, validates explicit overrides before package installation, and prints the selected version. Explicit empty values and `latest` still fail with a clear error.

## 2. Install

Gateway mode is enabled by default. Create its authentication Secret first using the instructions below, or set `--set gateway.enabled=false` for the original interactive-only workspace. Gateway readiness stays false until Codex is logged in; use `kubectl exec` to complete the login.

```bash
helm upgrade --install codex ./codex-workspace \
  --namespace codex \
  --create-namespace
```

No OpenAI API-key Secret is required.

## 3. Enter the coding workspace

```bash
POD=$(kubectl -n codex get pod \
  -l app.kubernetes.io/instance=codex \
  -o jsonpath='{.items[0].metadata.name}')

kubectl -n codex exec -it "$POD" -- bash
```

## 4. Sign in with ChatGPT

Inside the Pod, start Codex:

```bash
codex
```

Follow the CLI sign-in flow and choose ChatGPT account sign-in.

For a remote/headless server environment, use device-code authentication:

```bash
codex login --device-auth
```

Then open the URL shown by the CLI in your browser, sign in to your ChatGPT account, and enter the one-time code. Device-code authentication may need to be enabled in your ChatGPT security/workspace settings.

After login, your Codex state is persisted at:

```text
/home/node/.codex
```

That directory is mounted from its own PVC, so deleting/recreating the Pod does not normally require signing in again as long as the same PVC remains and the authentication session is still valid.

## 5. Verify and use Codex

```bash
cd /workspace
codex
```

Inside an active Codex session, you can also use the CLI's status command where supported to inspect the current session/usage.

## 6. Clone a repository

Public repository:

```bash
cd /workspace
git clone https://github.com/example/project.git
cd project
codex
```

For a private repository, create a Kubernetes Secret containing your SSH files and enable `gitSsh` in `values.yaml`.

## Storage

The default chart creates three persistent areas:

- `/workspace` — source code and repositories, 20 GiB by default.
- `/home/node` — shell history, npm cache, Git config and other home-directory data, 5 GiB by default.
- `/home/node/.codex` — Codex login/session/configuration, 1 GiB by default and stored on a dedicated PVC.

The dedicated Codex-state PVC intentionally contains authentication material. Treat it as sensitive data and do not share the same PVC between unrelated users.

## Security defaults

- Runs as non-root UID/GID 1000.
- Drops Linux capabilities.
- Disables privilege escalation.
- Does not mount the Kubernetes service-account token by default.
- Does not require or inject `OPENAI_API_KEY`.
- Keeps Codex login/session state on a dedicated PVC.

Do not mount `/var/run/docker.sock` into this Pod unless you explicitly accept the host-level security implications.

## Upgrade from the API-key edition

If you previously deployed the older chart:

1. Remove any obsolete `openai:` values override.
2. The Kubernetes Secret containing `OPENAI_API_KEY` is no longer referenced by this chart.
3. Upgrade the release:

```bash
helm upgrade --install codex ./codex-workspace \
  --namespace codex
```

4. Enter the Pod and sign in to ChatGPT once.

You may delete the old API-key Secret separately after confirming no other workloads use it.

## HTTP gateway

The image includes a FastAPI gateway running as the existing `node` user. Each authenticated request starts a new `codex exec --ephemeral` process, passes the prompt through stdin, and reads only the final-message file. The server fixes the sandbox to `read-only` and approval policy to `never`. Clients cannot supply commands, paths, models, or CLI flags. The default working directory is `/opt/codex-gateway/workspace`, separate from the interactive repositories in `/workspace`.

`HOME` and `CODEX_HOME` point at the existing PVC mounts, so Codex reuses the server's saved login. The gateway bearer token is unrelated to OpenAI authentication and is excluded from the Codex subprocess environment. Do not run multiple gateway workers or replicas: admission control is in memory, and the existing login/workspace volumes are shared.

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Process liveness; no inference or login call |
| `GET /ready` | Runs `codex login status`, cached for five seconds; 200 or 503 |
| `POST /v1/generate` | Requires `Authorization: Bearer <gateway-token>` |

Request: `{"requestId":"unique-per-call","prompt":"..."}`

Success: `{"requestId":"unique-per-call","output":"final assistant message"}`

Requests are limited to 1 MiB, including JSON overhead. Final output is limited to 2 MiB. One request executes at a time; excess requests receive 429 before inference begins. Invalid authentication returns 401, malformed input 422, unavailable CLI/login 503, execution failure 502, and execution timeout 504. Responses and logs exclude prompts, CLI stderr, and tokens. A disconnected client cancels execution and stops the process tree before another request can run.

Readiness checks local login state; revoked upstream credentials and account quota can still fail during inference. `/ready` must not be used as proof that the account has remaining quota. No durable queue, result storage, idempotency, or automatic generation retry is provided. If the connection drops after a request is sent, its outcome can be unknown.

### Provision the gateway token

Run in a trusted Linux terminal with the correct kubectl context. This creates a 64-character token without printing it or putting it in Helm values:

```bash
umask 077
TOKEN_FILE=$(mktemp)
openssl rand -hex 32 | tr -d '\n' > "$TOKEN_FILE"
kubectl -n codex create secret generic codex-gateway-auth --from-file=token="$TOKEN_FILE"
rm -f -- "$TOKEN_FILE"
```

If the Secret already exists, reuse it. The gateway requires an ASCII token of at least 32 characters without whitespace. When rotating it, update both the server and client and restart their Pods; Secret environment variables are read on process startup. Never commit the token or the saved Codex auth files.

### Upgrade the existing release

`scripts/deploy-gateway.sh` performs login/version/flag checks on the existing Pod, builds and pushes the image with that exact Codex version, creates the gateway Secret only if absent, and upgrades the existing release with automatic rollback on failure. It preserves user-supplied Helm values and the release's PVC names. Run it on a Linux host with authenticated kubectl, Helm 3, Docker, and registry access:

```bash
export NAMESPACE=codex
export RELEASE=codex
export ORCHESTRATOR_NAMESPACE=infra  # Set the actual orchestrator namespace.
export IMAGE_TAG=3
export PUSH_IMAGE=YOUR_REACHABLE_REGISTRY/codex-workspace:3
export PULL_REPOSITORY=registry.registry.svc.cluster.local:5000/codex-workspace
bash scripts/deploy-gateway.sh
```

The push and pull names must point to the **same registry/repository**. Kubernetes Service DNS often resolves inside Pods only; Docker on the build host may need a different address or a registry port-forward. Authenticate to that registry before running the script. An old Codex version missing required flags fails preflight; select and validate a compatible version before upgrading it separately.

For a manual Helm upgrade, supply `helm get values` output as a values file so new chart defaults are merged. Avoid `--reuse-values` when upgrading from the older chart that lacks `gateway.*` values. Review any saved values privately because they may include existing environment settings.

### Connect the orchestrator inside Kubernetes

The default endpoint is `http://codex-gateway.codex.svc.cluster.local:8080`. Set `gateway.networkPolicy.allowedNamespace` to the orchestrator's namespace; it defaults to the Codex release namespace. The orchestrator Pod must have the label `app.kubernetes.io/name: ai-orchestrator`. The NetworkPolicy allows ingress on the gateway port from Pods matching both that namespace and label. Enforcement requires a CNI that implements NetworkPolicy; it does not encrypt traffic. No egress restriction is added, so Codex can reach its upstream service.

Add these fields to the orchestrator Deployment, with the gateway token provisioned in **the orchestrator's namespace** as well. A `secretKeyRef` cannot reference a different namespace:

```yaml
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ai-orchestrator
    spec:
      containers:
        - name: ai-orchestrator
          env:
            - name: LLM_PROVIDER
              value: codex
            - name: CODEX_TRANSPORT
              value: http
            - name: CODEX_REMOTE_URL
              value: http://codex-gateway.codex.svc.cluster.local:8080
            - name: CODEX_REMOTE_TOKEN
              valueFrom:
                secretKeyRef:
                  name: codex-gateway-auth
                  key: token
            - name: CODEX_REMOTE_TIMEOUT_SECONDS
              value: "630"
```

Configure the same token securely in both namespaces. Keep the gateway execution deadline at 600 seconds and the client deadline at 630 seconds, or increase them together. The SDLC workflow can perform a second request to repair invalid JSON; allow roughly 1260 seconds plus overhead at the orchestrator's caller/proxy, or configure shorter deadlines consistently.

### Windows development and verification

From the ai-orchestrator repository, use `scripts/dev-port-forward.ps1` and `scripts/configure-codex-dev.ps1`. Both support a local kubeconfig or `-SshHost tarchunk@192.168.1.51`, using the remote host's kubectl context. SSH authentication is completed in the user's terminal; passwords and private keys do not belong in the scripts.

After deployment, check `/health` and `/ready` through port-forward, run the example `/generate` request in the orchestrator README, then test the same call from a labeled orchestrator Pod inside the cluster. During a planned restart, confirm that the PVC-backed login remains available; restart port-forward after the selected Pod terminates. Test rejected credentials and simultaneous requests as well. These live checks require a deployed image and valid server login.

The local tests use a fake CLI for subprocess behavior and do not make model calls:

```bash
python -m pip install -r gateway/requirements.txt httpx
python -m unittest discover -s tests -v
helm lint .
helm template codex . --namespace codex
```
