#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../config/release.env
source "$project_dir/config/release.env"
state_dir=/var/lib/pi-k3s-lab
kubelet_config=/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/10-lab.conf

fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'Run as root on the Pi.'
[[ $(uname -m) == aarch64 ]] || fail 'This installer targets ARM64 only.'
grep -qw memory /sys/fs/cgroup/cgroup.controllers || fail 'Enable memory cgroup and reboot first.'
ip link show eth0 >/dev/null || fail 'Expected eth0; review config/k3s.yaml for this host.'
exec 9>/run/lock/pi-k3s-lab-install.lock
flock -n 9 || fail 'Another installation is already running.'

if [[ -f "$state_dir/installed.sha256" ]]; then
    # Re-running is a no-op, not an implicit upgrade or config overwrite.
    sha256sum --check "$state_dir/installed.sha256"
    printf '%s  %s\n' "$K3S_ARM64_SHA256" /usr/local/bin/k3s | sha256sum --check -
    cmp "$project_dir/config/k3s.yaml" /etc/rancher/k3s/config.yaml
    cmp "$project_dir/config/10-lab.conf" "$kubelet_config"
    systemctl enable --now k3s
    printf 'Existing installation matches; no restart requested.\n'
    exit 0
fi

for path in /usr/local/bin/k3s /etc/rancher/k3s /var/lib/rancher/k3s \
    /etc/systemd/system/k3s.service /etc/systemd/system/k3s.service.env \
    /etc/systemd/system/k3s.service.d \
    /etc/default/k3s /etc/sysconfig/k3s; do
    [[ ! -e "$path" ]] || fail "Refusing to overwrite an unmanaged installation: $path"
done

download_dir=$(mktemp -d /tmp/pi-k3s-download.XXXXXXXX)
cleanup() {
    # Only these two files are created here; never remove a broad directory.
    rm -f -- "$download_dir/k3s-arm64" "$download_dir/install.sh"
    rmdir -- "$download_dir"
}
trap cleanup EXIT
url_version=${K3S_VERSION/+/%2B}
curl --fail --location --silent --show-error --retry 2 --connect-timeout 15 --max-time 300 \
    "https://github.com/k3s-io/k3s/releases/download/$url_version/k3s-arm64" \
    --output "$download_dir/k3s-arm64"
curl --fail --location --silent --show-error --retry 2 --connect-timeout 15 --max-time 60 \
    "https://raw.githubusercontent.com/k3s-io/k3s/$url_version/install.sh" \
    --output "$download_dir/install.sh"
printf '%s  %s\n' "$K3S_ARM64_SHA256" "$download_dir/k3s-arm64" \
    "$K3S_INSTALL_SHA256" "$download_dir/install.sh" | sha256sum --check -

install -d -m 0700 "$state_dir" /etc/rancher/k3s
install -d -m 0755 "$(dirname -- "$kubelet_config")"
install -m 0600 "$project_dir/config/k3s.yaml" /etc/rancher/k3s/config.yaml
install -m 0644 "$project_dir/config/10-lab.conf" "$kubelet_config"
install -m 0755 "$download_dir/k3s-arm64" /usr/local/bin/k3s

# Let the pinned upstream installer generate its standard systemd unit only.
# No inherited tokens/proxies, symlinks, killall/uninstall scripts, or auto-start.
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    INSTALL_K3S_BIN_DIR=/usr/local/bin INSTALL_K3S_BIN_DIR_READ_ONLY=true \
    INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_SKIP_START=true \
    sh "$download_dir/install.sh" server
sha256sum /usr/local/bin/k3s /etc/rancher/k3s/config.yaml "$kubelet_config" \
    /etc/systemd/system/k3s.service /etc/systemd/system/k3s.service.env \
    > "$state_dir/installed.sha256"
chmod 0600 "$state_dir/installed.sha256"
systemctl daemon-reload
systemctl enable k3s
systemctl start --no-block k3s
printf 'K3s is starting. Run make check to wait for readiness.\n'
