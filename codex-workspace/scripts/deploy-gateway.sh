#!/usr/bin/env bash
# Run on a Linux build host with authenticated kubectl, Helm 3, and Docker.
set -euo pipefail

CHART_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-codex}"
RELEASE="${RELEASE:-codex}"
ORCHESTRATOR_NAMESPACE="${ORCHESTRATOR_NAMESPACE:-$NAMESPACE}"
TOKEN_SECRET="${TOKEN_SECRET:-codex-gateway-auth}"
IMAGE_TAG="${IMAGE_TAG:-3}"
# PUSH_IMAGE must be reachable by Docker on the build host. PULL_REPOSITORY is
# the registry name Kubernetes uses, which may be a different DNS name.
: "${PUSH_IMAGE:?Set PUSH_IMAGE to the complete image:tag that Docker can push}"
: "${PULL_REPOSITORY:?Set PULL_REPOSITORY to the image repository Kubernetes can pull}"
if [[ "$PUSH_IMAGE" != *":$IMAGE_TAG" ]]; then
    echo 'PUSH_IMAGE must use the same tag as IMAGE_TAG.' >&2
    exit 1
fi
for tool in kubectl helm docker openssl; do command -v "$tool" >/dev/null; done

POD="$(kubectl -n "$NAMESPACE" get pods -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/name=codex-workspace" -o jsonpath='{.items[0].metadata.name}')"
test -n "$POD"
kubectl -n "$NAMESPACE" exec "$POD" -c codex -- codex login status
CODEX_VERSION="$(kubectl -n "$NAMESPACE" exec "$POD" -c codex -- codex --version | awk '{print $2}')"
if [[ ! "$CODEX_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.+-][A-Za-z0-9.+-]+)?$ ]]; then
    echo 'Could not determine an exact Codex version from the existing Pod.' >&2
    exit 1
fi

# Confirm required flags before replacing the existing workspace image.
EXEC_HELP="$(kubectl -n "$NAMESPACE" exec "$POD" -c codex -- codex exec --help)"
for flag in --ephemeral --output-last-message --sandbox --skip-git-repo-check; do
    if [[ "$EXEC_HELP" != *"$flag"* ]]; then
        echo "The existing Codex version does not support required flag $flag." >&2
        exit 1
    fi
done

docker build --build-arg "CODEX_VERSION=$CODEX_VERSION" -t "$PUSH_IMAGE" "$CHART_DIR"
docker push "$PUSH_IMAGE"

umask 077
WORK_DIR="$(mktemp -d)"
trap 'rm -f -- "$WORK_DIR/token" "$WORK_DIR/values.yaml"; rmdir -- "$WORK_DIR"' EXIT
# Preserve user-supplied Helm values and PVC names while adding new defaults.
# Do not use --reuse-values: it can retain old chart defaults without gateway.*.
helm get values "$RELEASE" -n "$NAMESPACE" -o yaml > "$WORK_DIR/values.yaml"

if ! kubectl -n "$NAMESPACE" get secret "$TOKEN_SECRET" >/dev/null 2>&1; then
    openssl rand -hex 32 | tr -d '\n' > "$WORK_DIR/token"
    kubectl -n "$NAMESPACE" create secret generic "$TOKEN_SECRET" --from-file="token=$WORK_DIR/token"
fi

helm lint "$CHART_DIR" -f "$WORK_DIR/values.yaml"
helm upgrade "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" \
    -f "$WORK_DIR/values.yaml" \
    --set gateway.enabled=true \
    --set-string "gateway.existingSecret=$TOKEN_SECRET" \
    --set-string "gateway.networkPolicy.allowedNamespace=$ORCHESTRATOR_NAMESPACE" \
    --set-string "image.repository=$PULL_REPOSITORY" \
    --set-string "image.tag=$IMAGE_TAG" \
    --atomic --wait --timeout 10m

kubectl -n "$NAMESPACE" get pods -l "app.kubernetes.io/instance=$RELEASE" -o wide
echo 'Gateway deployed. Configure the orchestrator token Secret and pod label before testing inside the cluster.'
