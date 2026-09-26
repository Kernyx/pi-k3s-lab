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
active_release=/var/lib/pi-k3s-lab/deployed-release.json
release_file=${1:-}
if [[ -z $release_file && -f $active_release ]]; then
    sha256sum --check "$active_release.sha256"
    release_file=$active_release
fi
if [[ -n $release_file ]]; then
    release_values=$(python3 "$project_dir/scripts/release.py" "$release_file")
    image=$(printf '%s\n' "$release_values" | head -n 1)
    version=$(printf '%s\n' "$release_values" | tail -n 1)
    pull_policy=IfNotPresent
    # Download and check provenance before changing any live Kubernetes resource.
    timeout 180 /usr/local/bin/k3s crictl pull "$image"
    inspection=$(mktemp /var/lib/pi-k3s-lab/image-inspection.XXXXXXXX)
    /usr/local/bin/k3s crictl inspecti "$image" > "$inspection"
    python3 "$project_dir/scripts/release.py" "$release_file" "$inspection"
else
    version="src-$(python3 "$project_dir/scripts/source-version.py")"
    image="docker.io/pi-k3s-lab/home-portal:$version"
    pull_policy=Never
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        docker build --build-arg "APP_VERSION=$version" --tag "$image" "$project_dir"
    fi
    # Docker and k3s use different image stores. Import the native bootstrap build.
    if ! /usr/local/bin/k3s ctr images list -q | grep -Fxq "$image"; then
        docker save "$image" | /usr/local/bin/k3s ctr images import -
    fi
fi

if kubectl -n homelab get deployment home-portal >/dev/null 2>&1; then
    snapshot_output=$(python3 "$project_dir/scripts/app_state.py" --snapshot-held-lock)
    printf '%s\n' "$snapshot_output"
    backup_dir=${snapshot_output#Verified private snapshot: }
    [[ $backup_dir =~ ^/var/lib/pi-k3s-lab/app-snapshot\.[a-zA-Z0-9_]+$ ]] || exit 1
else
    # Initial bootstrap has no previous Deployment/Service to restore.
    backup_dir=$(mktemp -d /var/lib/pi-k3s-lab/app-before-deploy.XXXXXXXX)
    chmod 0700 "$backup_dir"
    install -m 0600 "$config_file" "$backup_dir/links.json"
    sha256sum "$backup_dir"/* > "$backup_dir/SHA256SUMS"
    sha256sum --check "$backup_dir/SHA256SUMS"
fi
printf 'Verified pre-deployment snapshot: %s\n' "$backup_dir"

kubectl apply -f "$project_dir/k8s/namespace.yaml"
config_version=$(sha256sum "$config_file" | cut -c1-12)
config_name="home-portal-links-$config_version"
kubectl -n homelab create configmap "$config_name" --from-file="links.json=$config_file" \
    --dry-run=client -o json \
    | kubectl label --local -f - app.kubernetes.io/part-of=pi-k3s-lab -o json \
    | kubectl patch --local -f - --type=merge -p '{"immutable":true}' -o json \
    | kubectl apply -f -
kubectl create --dry-run=client -f "$project_dir/k8s/deployment.yaml" -o json \
    | python3 "$project_dir/scripts/render-deployment.py" "$image" "$config_name" "$pull_policy" \
    | kubectl apply -f -
kubectl apply -f "$project_dir/k8s/service.yaml"
kubectl -n homelab rollout status deployment/home-portal --timeout=180s
bash "$project_dir/scripts/check-app.sh"
# Check every ready replica directly: a single Service response is insufficient.
kubectl -n homelab get pods -l app=home-portal -o json \
    | python3 "$project_dir/scripts/check-replicas.py" "$version" "$image"
if [[ -n $release_file ]]; then
    pending=$(mktemp /var/lib/pi-k3s-lab/release-pending.XXXXXXXX)
    install -m 0600 "$release_file" "$pending"
    mv "$pending" "$active_release"
    sha256sum "$active_release" > "$active_release.sha256"
    sha256sum --check "$active_release.sha256"
fi
printf 'Deployed version %s; rollback snapshot: %s\n' "$version" "$backup_dir"
