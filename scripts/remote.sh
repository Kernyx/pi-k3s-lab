#!/usr/bin/env bash
set -euo pipefail
action=${1:?Expected a Makefile action}
: "${SSH_HOST:?Set SSH_HOST to your own SSH alias or user@host}"
[[ $SSH_HOST =~ ^[a-zA-Z0-9][a-zA-Z0-9_.@-]*$ ]] || { printf 'Invalid SSH_HOST\n' >&2; exit 1; }
case "$action" in prepare|up|check|smoke|deploy|release|drill|rollback|app-check|configure|open|observe|load) ;; *) printf 'Unknown action\n' >&2; exit 1 ;; esac
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
if [[ $action == open ]]; then
    printf 'Open http://127.0.0.1:18080 (Grafana tunnel: http://127.0.0.1:13000). Ctrl+C closes the tunnels.\n'
    # A remote PTY makes Ctrl+C / SSH disconnect terminate sudo's port-forward too.
    exec ssh -tt "${ssh_options[@]}" -o ExitOnForwardFailure=yes \
        -L 127.0.0.1:18080:127.0.0.1:18080 -L 127.0.0.1:13000:127.0.0.1:3000 "$SSH_HOST" \
        'sudo -n k3s kubectl -n homelab port-forward --address=127.0.0.1 service/home-portal 18080:80'
fi
if [[ $action == rollback ]]; then
    : "${SNAPSHOT_DIR:?Set SNAPSHOT_DIR to a verified private app-snapshot directory on the Pi}"
    [[ $SNAPSHOT_DIR =~ ^/var/lib/pi-k3s-lab/app-snapshot\.[a-zA-Z0-9_]+$ ]] || { printf 'Invalid snapshot path\n' >&2; exit 1; }
fi
if [[ $action == release ]]; then
    if [[ -n ${RUN_ID:-} ]]; then
        [[ $RUN_ID =~ ^[0-9]+$ ]] || { printf 'Invalid RUN_ID\n' >&2; exit 1; }
        artifact_dir=$(mktemp -d /tmp/pi-k3s-release.XXXXXXXX)
        gh run view "$RUN_ID" --repo Kernyx/pi-k3s-lab --json conclusion,event,headBranch,headSha \
            | python3 "$project_dir/scripts/check-run.py" > "$artifact_dir/revision"
        gh run download "$RUN_ID" --repo Kernyx/pi-k3s-lab --name home-portal-release --dir "$artifact_dir"
        RELEASE_FILE="$artifact_dir/release.json"
        python3 "$project_dir/scripts/release.py" "$RELEASE_FILE"
        python3 -c 'import json,sys; from pathlib import Path; assert json.loads(Path(sys.argv[1]).read_text())["revision"] == Path(sys.argv[2]).read_text().strip(), "Artifact revision differs from workflow commit"' "$RELEASE_FILE" "$artifact_dir/revision"
    else
        : "${RELEASE_FILE:?Set RUN_ID or RELEASE_FILE to a public release descriptor}"
        python3 "$project_dir/scripts/release.py" "$RELEASE_FILE"
    fi
fi
remote_dir=$(ssh "${ssh_options[@]}" "$SSH_HOST" 'mktemp -d /tmp/pi-k3s-lab.XXXXXXXX')
[[ $remote_dir =~ ^/tmp/pi-k3s-lab\.[a-zA-Z0-9]+$ ]] || { printf 'Unexpected staging path\n' >&2; exit 1; }
# A small staging directory is retained for diagnosis; it contains no credentials.
scp "${ssh_options[@]}" -r "$project_dir/scripts" "$project_dir/config" "$project_dir/app" \
    "$project_dir/k8s" "$project_dir/monitoring" "$project_dir/Dockerfile" "$project_dir/.dockerignore" "$SSH_HOST:$remote_dir/"
if [[ $action == release ]]; then
    scp "${ssh_options[@]}" "$RELEASE_FILE" "$SSH_HOST:$remote_dir/release.json"
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/deploy-app.sh' '$remote_dir/release.json'"
    exit 0
fi
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
    drill) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n python3 '$remote_dir/scripts/rollout-drill.py'" ;;
    rollback) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n python3 '$remote_dir/scripts/app_state.py' '$SNAPSHOT_DIR'" ;;
    app-check) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n bash '$remote_dir/scripts/check-app.sh'" ;;
    observe) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n python3 '$remote_dir/scripts/observe.py'" ;;
    load) ssh "${ssh_options[@]}" "$SSH_HOST" "sudo -n python3 '$remote_dir/scripts/load-portal.py'" ;;
esac
