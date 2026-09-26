#!/usr/bin/env bash
set -euo pipefail
action=${1:?Expected prepare, up, check, or smoke}
: "${SSH_HOST:?Set SSH_HOST to your own SSH alias or user@host}"
[[ $SSH_HOST =~ ^[a-zA-Z0-9][a-zA-Z0-9_.@-]*$ ]] || { printf 'Invalid SSH_HOST\n' >&2; exit 1; }
case "$action" in prepare|up|check|smoke) ;; *) printf 'Unknown action\n' >&2; exit 1 ;; esac
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
remote_dir=$(ssh "${ssh_options[@]}" "$SSH_HOST" 'mktemp -d /tmp/pi-k3s-lab.XXXXXXXX')
[[ $remote_dir =~ ^/tmp/pi-k3s-lab\.[a-zA-Z0-9]+$ ]] || { printf 'Unexpected staging path\n' >&2; exit 1; }
# A small staging directory is retained for diagnosis; it contains no credentials.
scp "${ssh_options[@]}" -r "$project_dir/scripts" "$project_dir/config" "$SSH_HOST:$remote_dir/"
# remote_dir is validated above and intentionally expanded on the client.
# shellcheck disable=SC2029
case "$action" in
    prepare) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n python3 '$remote_dir/scripts/prepare-host.py'" ;;
    up) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/install.sh' && sudo -n bash '$remote_dir/scripts/check.sh'" ;;
    check) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/check.sh'" ;;
    smoke) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/smoke.sh'" ;;
esac
