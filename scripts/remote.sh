#!/usr/bin/env bash
set -euo pipefail
action=${1:?Expected prepare, up, check, smoke, deploy, app-check, configure, or open}
: "${SSH_HOST:?Set SSH_HOST to your own SSH alias or user@host}"
[[ $SSH_HOST =~ ^[a-zA-Z0-9][a-zA-Z0-9_.@-]*$ ]] || { printf 'Invalid SSH_HOST\n' >&2; exit 1; }
case "$action" in prepare|up|check|smoke|deploy|app-check|configure|open) ;; *) printf 'Unknown action\n' >&2; exit 1 ;; esac
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
if [[ $action == open ]]; then
    printf 'Open http://127.0.0.1:18080 (Grafana tunnel: http://127.0.0.1:13000). Ctrl+C closes the tunnels.\n'
    exec ssh "${ssh_options[@]}" -o ExitOnForwardFailure=yes \
        -L 127.0.0.1:18080:127.0.0.1:18080 -L 127.0.0.1:13000:127.0.0.1:3000 "$SSH_HOST" \
        'sudo -n k3s kubectl -n homelab port-forward --address=127.0.0.1 service/home-portal 18080:80'
fi
remote_dir=$(ssh "${ssh_options[@]}" "$SSH_HOST" 'mktemp -d /tmp/pi-k3s-lab.XXXXXXXX')
[[ $remote_dir =~ ^/tmp/pi-k3s-lab\.[a-zA-Z0-9]+$ ]] || { printf 'Unexpected staging path\n' >&2; exit 1; }
# A small staging directory is retained for diagnosis; it contains no credentials.
scp "${ssh_options[@]}" -r "$project_dir/scripts" "$project_dir/config" "$project_dir/app" \
    "$project_dir/k8s" "$project_dir/Dockerfile" "$project_dir/.dockerignore" "$SSH_HOST:$remote_dir/"
if [[ $action == configure ]]; then
    : "${LINKS_FILE:?Set LINKS_FILE to a private JSON file outside the repository}"
    python3 "$project_dir/app/server.py" --check-config "$LINKS_FILE"
    # Place private data in a separate 0700 directory, never the image build context.
    private_dir=$(ssh "${ssh_options[@]}" "$SSH_HOST" 'mktemp -d /tmp/pi-k3s-links.XXXXXXXX')
    [[ $private_dir =~ ^/tmp/pi-k3s-links\.[a-zA-Z0-9]+$ ]] || exit 1
    scp "${ssh_options[@]}" "$LINKS_FILE" "$SSH_HOST:$private_dir/links.json"
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/configure-app.sh' '$private_dir/links.json'"
    exit 0
fi
# remote_dir is validated above and intentionally expanded on the client.
# shellcheck disable=SC2029
case "$action" in
    prepare) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n python3 '$remote_dir/scripts/prepare-host.py'" ;;
    up) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/install.sh' && sudo -n bash '$remote_dir/scripts/check.sh' && sudo -n bash '$remote_dir/scripts/deploy-app.sh'" ;;
    check) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/check.sh'" ;;
    smoke) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/smoke.sh'" ;;
    deploy) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/deploy-app.sh'" ;;
    app-check) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/check-app.sh'" ;;
esac
