# parallel-ai-test-orchestrator

Kubernetes manifests for the parallel AI test orchestrator. Argo CD manages
the root YAML files in this directory; `argocd-app.yaml` is applied only once
and is excluded from the application's source.

## Bootstrap

1. Populate the `AI_TEST_*` fields documented in the application repository's
   `docs/jenkins.md`. Jenkins creates and updates the runtime Secrets directly
   from Vault; the Secret objects and their values are not stored in this
   GitOps directory, so Argo CD does not reconcile them. Argo CD manages the
   non-secret `ai-test-repository-policies` ConfigMap and the namespaced Jenkins
   Secret RBAC from `jenkins-secret-rbac.yaml`.
2. Confirm `truenas-nfs-storage` supports `ReadWriteMany`; the gateway and
   reconciler share the `ai-test-artifacts` PVC.
3. Apply the Argo CD application:

   ```console
   kubectl apply -f parallel-ai-test-orchestrator/argocd-app.yaml
   ```

Jenkins updates the immutable image tags in `gateway.yaml` and
`reconciler-cronjob.yaml`. Argo CD automatically applies those commits.
