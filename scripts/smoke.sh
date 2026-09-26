#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { printf 'Run as root on the Pi.\n' >&2; exit 1; }
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
kubectl() { /usr/local/bin/k3s kubectl --request-timeout=30s "$@"; }
namespace=pi-lab-checks
if kubectl get namespace "$namespace" >/dev/null 2>&1; then
    owner=$(kubectl get namespace "$namespace" -o 'jsonpath={.metadata.labels.app\.kubernetes\.io/part-of}')
    [[ $owner == pi-k3s-lab ]] || { printf 'Existing namespace is not owned by this lab.\n' >&2; exit 1; }
else
    kubectl create namespace "$namespace"
    kubectl label namespace "$namespace" app.kubernetes.io/part-of=pi-k3s-lab \
        pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/enforce-version=v1.36
fi
job=$(kubectl create -f "$project_dir/config/smoke-job.yaml" -o name)
[[ $job =~ ^job.batch/smoke-[a-z0-9]+$ ]] || { printf 'Unexpected job name.\n' >&2; exit 1; }
if ! kubectl -n "$namespace" wait --for=condition=Complete "$job" --timeout=150s; then
    kubectl -n "$namespace" get pods
    kubectl -n "$namespace" logs "$job" || true
    printf 'Smoke test failed; job retained temporarily for diagnosis.\n' >&2
    exit 1
fi
kubectl -n "$namespace" logs "$job"
# Only delete the uniquely named Job created by this invocation, never the namespace.
kubectl -n "$namespace" delete "$job" --wait=true --timeout=30s
