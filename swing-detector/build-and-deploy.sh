#!/bin/bash
# build-and-deploy.sh
# Build image → push ไป internal registry → deploy ด้วย Helm

set -e

REGISTRY="registry.registry.svc.cluster.local:5000"
IMAGE_NAME="swing-detector"
TAG="${1:-1}"                          # รับ tag จาก argument, default = 1
NAMESPACE="infra"
RELEASE_NAME="swing-detector"

echo "▶ Building image: ${REGISTRY}/${IMAGE_NAME}:${TAG}"
docker build -t "${REGISTRY}/${IMAGE_NAME}:${TAG}" ./app

echo "▶ Pushing to registry..."
docker push "${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "▶ Deploying with Helm..."
helm upgrade --install "${RELEASE_NAME}" ./swing-detector \
  --namespace "${NAMESPACE}" \
  --create-namespace \
  --set image.tag="${TAG}" \
  --wait \
  --timeout 2m

echo "✅ Done! Pod status:"
kubectl get pods -n "${NAMESPACE}" -l app=swing-detector
