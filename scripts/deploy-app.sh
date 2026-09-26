#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { printf 'Run as root on the Pi.\n' >&2; exit 1; }
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
kubectl() { /usr/local/bin/k3s kubectl --request-timeout=30s "$@"; }
exec 9>/run/lock/pi-k3s-lab-app.lock
flock -n 9 || { printf 'Another app deployment is running.\n' >&2; exit 1; }

if kubectl get namespace homelab >/dev/null 2>&1; then
    owner=$(kubectl get namespace homelab -o 'jsonpath={.metadata.labels.app\.kubernetes\.io/part-of}')
    [[ $owner == pi-k3s-lab ]] || { printf 'Namespace homelab is not owned by this lab.\n' >&2; exit 1; }
fi
config_file=/etc/pi-k3s-lab/links.json
if [[ ! -f "$config_file" ]]; then
    install -d -m 0700 /etc/pi-k3s-lab
    install -m 0600 "$project_dir/app/links.example.json" "$config_file"
fi
python3 "$project_dir/app/server.py" --check-config "$config_file"
version=$(python3 "$project_dir/scripts/source-version.py")
image="docker.io/pi-k3s-lab/home-portal:src-$version"
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build --build-arg "APP_VERSION=src-$version" --tag "$image" "$project_dir"
fi
# Docker and k3s use different image stores. Import the exact native ARM64 build.
if ! /usr/local/bin/k3s ctr images list -q | grep -Fxq "$image"; then
    docker save "$image" | /usr/local/bin/k3s ctr images import -
fi

backup_dir=$(mktemp -d /var/lib/pi-k3s-lab/app-before-deploy.XXXXXXXX)
chmod 0700 "$backup_dir"
kubectl -n homelab get deployment home-portal -o yaml > "$backup_dir/deployment.yaml" 2>/dev/null || true
kubectl -n homelab get service home-portal -o yaml > "$backup_dir/service.yaml" 2>/dev/null || true
install -m 0600 "$config_file" "$backup_dir/links.json"
sha256sum "$backup_dir"/* > "$backup_dir/SHA256SUMS"
sha256sum --check "$backup_dir/SHA256SUMS"

kubectl apply -f "$project_dir/k8s/namespace.yaml"
config_version=$(sha256sum "$config_file" | cut -c1-12)
config_name="home-portal-links-$config_version"
kubectl -n homelab create configmap "$config_name" --from-file="links.json=$config_file" \
    --dry-run=client -o json \
    | kubectl label --local -f - app.kubernetes.io/part-of=pi-k3s-lab -o json \
    | kubectl patch --local -f - --type=merge -p '{"immutable":true}' -o json \
    | kubectl apply -f -
kubectl create --dry-run=client -f "$project_dir/k8s/deployment.yaml" -o json \
    | python3 "$project_dir/scripts/render-deployment.py" "$image" "$config_name" \
    | kubectl apply -f -
kubectl apply -f "$project_dir/k8s/service.yaml"
kubectl -n homelab rollout status deployment/home-portal --timeout=180s
printf 'Deployed version src-%s; rollback snapshot: %s\n' "$version" "$backup_dir"
bash "$project_dir/scripts/check-app.sh"
