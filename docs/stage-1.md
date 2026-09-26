# Stage 1: a verified single-node foundation

Verified on 2026-09-26, Raspberry Pi 5, 8 GiB, ARM64, Raspberry Pi OS / Debian 13.
No live addresses, credentials, kubeconfigs or disk identifiers are published.

## What changed

1. Added `cgroup_memory=1 cgroup_enable=memory` to the existing boot command line.
   Saved and SHA-256-verified the original on the Pi and on a separate computer.
2. Rebooted in a maintenance window with both backup services inactive.
   The memory controller appeared in cgroup v2. Boot parameters were not replaced
   wholesale. The HDD, fstab, VPN settings and existing application configs were
   not changed by this stage.
3. Installed the pinned upstream ARM64 k3s binary and its standard systemd unit.
   The upstream installer was pinned and checksum-verified too. Its automatic
   start, symlink creation and destructive helper generation were disabled.
4. Enabled one server with the default SQLite datastore, separate containerd,
   CoreDNS, local-path-provisioner and metrics-server. Disabled Traefik/ServiceLB.
5. Verified readiness, pod networking, actual cgroup memory/swap limits, repeat
   installation, admin file permissions and coexistence with existing services.

## Why the first check needed a fix

The first `make up` reached Node Ready and immediately tried to watch the CoreDNS
Deployment. The add-on controller had not created the object yet; kubectl returned
NotFound. The check failed honestly, rather than reporting a working cluster.

The corrected check waits, with a deadline, for the Deployment object to exist,
then waits for its rollout. These are different conditions:

- API readiness: the control plane can answer requests.
- Node readiness: kubelet registered a usable node.
- Deployment readiness: the desired application replicas passed their probes.
- Smoke success: a real pod can resolve DNS, perform HTTP and has enforced limits.

## Evidence

- `k3s.service`: start 15:09:09 UTC, active 15:09:41 UTC.
- System pod Ready transitions: local-path 15:12:05, CoreDNS 15:12:18,
  metrics-server 15:12:37 UTC. First full system readiness: **208 seconds**.
- `make check`: Node Ready, three successful rollouts, metrics API available,
  zero k3s service restarts.
- `make smoke`: PASS for internal/external DNS, HTTP egress, memory.max=33554432
  and memory.swap.max=0. The successful Job was deleted; its empty namespace remains.
- `/configz`: failSwapOn=false, NoSwap, systemReserved.memory=2Gi,
  kubeReserved.memory=512Mi, two 5Mi container log files.
- Repeated `make up`: all installed hashes and checked-in configs matched;
  service start remained 15:09:09 UTC.
- `k3s.service` MemoryCurrent sample: 998473728 bytes (~952 MiB).
  This is a cgroup sample, not the total Kubernetes/host memory footprint.
- Existing backup run succeeded in **9.074 s**; restore drill succeeded in
  **20.464 s**, including database integrity and an isolated Vaultwarden `/alive` check.
- Existing monitoring configuration/rule tests and HTTP health checks passed.
  Existing web applications responded HTTP 200.
- The existing notification proxy returned after its GUI session was started.
  An authenticated Telegram `getMe` request succeeded; **no new delivery test
  message was sent**. Proxy settings were not changed.

## Limits and remaining work

- A second full reboot with k3s installed has not been tested. The unit is enabled,
  but that alone is not an end-to-end reboot recovery test.
- The existing notification proxy depends on a graphical session, while the host's
  default boot target is non-graphical. The session was restored for this boot;
  persistent startup settings were deliberately left unchanged. Notifications
  therefore need attention again after a reboot until that separate issue is addressed.
- The HDD stays unused by Kubernetes after its failed SMART self-test.
- Local-path provisioner readiness does not prove persistent-volume recovery;
  no application PVC or durable data was added in this stage.
- No application rollout, load test, cluster-state restore or external heartbeat
  has been implemented yet.

## Files to explain in an interview

- `prepare-host.py`: preserve boot arguments; validate input; verify the backup;
  write a temporary file; atomically replace the original; require an explicit reboot.
- `install.sh`: preconditions, installation lock, pinned downloads, integrity checks,
  refusal to overwrite an unmanaged installation, a clean installer environment.
- `k3s.yaml`: cluster-level choices; `10-lab.conf`: kubelet resource/logging policy.
- `check.sh`: bounded waits for distinct readiness conditions.
- `smoke-job.yaml` / `smoke.sh`: a restricted, temporary workload that tests the real
  cluster rather than mocking its network or trusting an installation exit code.
- `remote.sh`: transfer only scripts/config, validate the SSH target and generated
  staging directory, keep credentials out of the repository.

Question: **Why does a Ready node not prove that an application is available?**
