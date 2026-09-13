# Codex Workspace Helm Chart — ChatGPT Login Edition

A persistent Kubernetes coding workspace with OpenAI Codex CLI that signs in with your ChatGPT account. This chart does **not** require an `OPENAI_API_KEY`.

Codex is available through ChatGPT plans, with usage limits depending on the plan. When you sign in to Codex with ChatGPT, usage follows your ChatGPT plan rather than API-key billing.

## 1. Build the image

```bash
docker build -t ghcr.io/YOUR_ORG/codex-workspace:latest .
docker push ghcr.io/YOUR_ORG/codex-workspace:latest
```

Change `image.repository` in `values.yaml` to match your registry.

## 2. Install

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
