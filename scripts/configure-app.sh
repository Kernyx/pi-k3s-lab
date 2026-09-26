#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { printf 'Run as root on the Pi.\n' >&2; exit 1; }
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
input=${1:?Expected a configuration file}
python3 "$project_dir/app/server.py" --check-config "$input"
exec 9>/run/lock/pi-k3s-lab-app.lock
flock -n 9 || { printf 'An app configuration/deployment is running.\n' >&2; exit 1; }
install -d -m 0700 /etc/pi-k3s-lab
if [[ -f /etc/pi-k3s-lab/links.json ]]; then
    backup_dir=$(mktemp -d /var/lib/pi-k3s-lab/links-before-configure.XXXXXXXX)
    chmod 0700 "$backup_dir"
    install -m 0600 /etc/pi-k3s-lab/links.json "$backup_dir/links.json"
    sha256sum "$backup_dir/links.json" > "$backup_dir/SHA256SUMS"
    sha256sum --check "$backup_dir/SHA256SUMS"
fi
install -m 0600 "$input" /etc/pi-k3s-lab/links.json
printf 'Private links saved on the Pi. Run make deploy to apply them.\n'
