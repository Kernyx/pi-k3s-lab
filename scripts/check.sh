#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { printf 'Run as root on the Pi.\n' >&2; exit 1; }

# Retry the API while the new service starts; every individual request is bounded.
deadline=$((SECONDS + 180))
until /usr/local/bin/k3s kubectl --request-timeout=5s get --raw=/readyz >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
        printf 'API readiness timed out. Inspect: journalctl -u k3s\n' >&2
        exit 1
    fi
    sleep 3
done
kubectl() { /usr/local/bin/k3s kubectl --request-timeout=30s "$@"; }
kubectl wait --for=condition=Ready node/pi-lab --timeout=180s
for deployment in coredns local-path-provisioner metrics-server; do
    # The node can become Ready before the packaged add-on controller creates these.
    deadline=$((SECONDS + 180))
    until kubectl -n kube-system get "deployment/$deployment" >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then
            printf 'Deployment %s was not created in time.\n' "$deployment" >&2
            exit 1
        fi
        sleep 3
    done
    kubectl -n kube-system rollout status "deployment/$deployment" --timeout=180s
done
kubectl get nodes
kubectl -n kube-system get pods
kubectl top nodes
systemctl show k3s -p ActiveState -p NRestarts -p MemoryCurrent
df -h /var/lib/rancher/k3s
