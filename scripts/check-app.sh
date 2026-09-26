#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { printf 'Run as root on the Pi.\n' >&2; exit 1; }
kubectl() { /usr/local/bin/k3s kubectl --request-timeout=30s "$@"; }
kubectl -n homelab rollout status deployment/home-portal --timeout=180s
cluster_ip=$(kubectl -n homelab get service home-portal -o 'jsonpath={.spec.clusterIP}')
for path in / /style.css /app.js /healthz /readyz /api/config /api/info; do
    # Exercise the ClusterIP service, not just a particular pod or port-forward.
    curl --fail --silent --show-error --max-time 5 "http://$cluster_ip$path" --output /dev/null
done
kubectl -n homelab get pods
kubectl -n homelab get endpointslices -l kubernetes.io/service-name=home-portal
# The metrics scrape follows readiness; allow the first scrape to arrive.
deadline=$((SECONDS + 60))
until kubectl -n homelab top pods; do
    (( SECONDS < deadline )) || { printf 'Pod metrics did not arrive in time.\n' >&2; exit 1; }
    sleep 3
done
printf 'PASS: home portal rollout and seven HTTP routes through its Service\n'
