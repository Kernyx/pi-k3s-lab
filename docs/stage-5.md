# Stage 5: per-pod observability and bounded load

## Data path

```text
root systemd helper -> Kubernetes EndpointSlices -> atomic targets.json
                                                     |
each ready portal pod /metrics ----------------------> Prometheus -> Grafana
```

The existing Docker monitoring uses host networking and can reach the k3s pod
network. It remains bound to localhost. No new stack, ingress, public port,
Grafana administrator credential or Prometheus kubeconfig was introduced.

Do not scrape only the load-balanced Service: different process-local counters
would appear under one target identity, producing false resets and rates.
The helper exports each ready, non-terminating pod with stable pod labels.
It refreshes after 15 seconds of inactivity; Prometheus scrapes every 15 seconds.
The file is replaced atomically and unchanged content is not rewritten.
API/discovery failure preserves the last good file; a successful empty discovery
writes `[]`. This distinction avoids losing working targets on a transient error.

## Commands and prerequisites

The application and selected registry release must already expose `/metrics`.
The integration deliberately expects the existing localhost stack from
[`vaultwarden-restore-drill`](https://github.com/Kernyx/vaultwarden-restore-drill),
at `/opt/vaultwarden-restore-drill/monitoring`, with Prometheus directory binds
and Grafana datasource UID `prometheus`. It is not a generic monitoring installer.

```sh
make release SSH_HOST=my-pi RUN_ID=<successful-run-id>
make observe SSH_HOST=my-pi
make open SSH_HOST=my-pi
# Open http://127.0.0.1:13000/d/pi-k3s-home-portal/pi-k3s-home-portal
# In another terminal, optional bounded test:
make load SSH_HOST=my-pi
```

`make observe` checks two metrics-capable endpoints before changes, seals a
private snapshot, installs its own fragment/helper/timer/dashboard and validates
the candidate with the running container's `promtool`. It adds only a managed
`scrape_config_files` include to the existing main config, preserving its jobs
and alerts. A validated SIGHUP reload does not restart the container. Activation
checks both the include and active scrape pool; targets and samples are checked
separately. Exceptions trigger file restoration. Conflicting existing includes
or unmanaged files under the integration's names are refused.

## Metrics and interpretation

| Metric | Meaning and scope |
| --- | --- |
| `portal_http_requests_total` | Business GET/HEAD handling; fixed route/method/status labels. Unknown paths become `other`. |
| `portal_http_request_duration_seconds` | Classic cumulative histogram including response socket write; not browser or network latency. |
| `portal_ready` | Valid configuration, not independent end-to-end availability. |
| `portal_process_resident_memory_bytes` | Current Linux VmRSS, not peak RSS or the entire container cgroup. |
| `portal_process_cpu_seconds_total` | Process CPU counter; `rate()` gives cores used, not percent automatically. |
| `portal_uptime_seconds`, `portal_build_info` | Process uptime and running Git revision. Pod identity is attached by discovery. |

Probes and `/metrics` do not affect business counters or the histogram. Private
link URLs, query strings and arbitrary request paths never become metric labels.
Unsupported HTTP methods and malformed requests handled by the base HTTP server
are outside these GET/HEAD counters. Readiness failures are still visible via
discovery and readiness/availability panels; this is not a complete HTTP audit.

The eight provisioned panels show readiness, scrapeability, business RPS,
non-200 RPS, estimated server p95, per-pod current RSS, CPU cores and revisions.
Rates use a two-minute window: allow at least two scrapes and expect smoothing,
not exact agreement with a 30-second client phase. `histogram_quantile` estimates
a percentile from bucket counts; client p95 is calculated from individual samples.
An idle histogram can have no meaningful p95; the dashboard must not invent one.

## Reading the implementation

- [`app/server.py`](../app/server.py): a lock makes counter/bucket/count/sum
  updates and scrape snapshots consistent across request threads. A duration
  contributes to every bucket whose upper bound includes it; `+Inf` equals count.
  `finally` records attempted handling even when writing a response fails.
  The status label is the response code selected, not proof of client delivery.
- [`scripts/discover-portal.py`](../scripts/discover-portal.py): validates namespace,
  Service label, pod reference, port and lab subnet before exporting targets.
  The privileged helper reads the existing root kubeconfig; Prometheus never does.
- [`scripts/observe.py`](../scripts/observe.py): fixed file allowlist, checksummed
  private snapshots, guarded main-config extension, validation, reload and undo.
- [`scripts/dashboard.py`](../scripts/dashboard.py): generates the same stable-UID
  dashboard on every installation; Grafana provisions it from its existing bind.
- [`scripts/load-portal.py`](../scripts/load-portal.py): only this owned Service,
  fresh TCP, bounded rate/concurrency/time, content and revision checks, no retries.

## Load method

Three 30-second phases target 5, 20 and 40 requests/s with 1, 2 and 4 workers.
Only `/api/info` is exercised through the ClusterIP from the Pi itself. Missed
schedule slots are skipped, never replayed as a catch-up burst. Any failed HTTP,
JSON or revision check stops the test; available host memory below 1 GiB also
stops it. Both replicas must appear in every phase. The app deployment lock
prevents simultaneous deployment/rollback by this project's scripts.

Raw samples and the report live in root-private `/var/lib/pi-k3s-lab/load-test.*`;
only aggregate results belong in the public repository. This does not measure
WAN/browser performance, maximum throughput, long-run reliability, TLS, database
workloads or resilience to Pi failure. A brief error-free run is not an SLA.

## Undo

Use the snapshot printed by your installation, not another host's name:

```sh
ssh my-pi 'sudo python3 /opt/pi-k3s-lab/monitoring/observe.py --restore /var/lib/pi-k3s-lab/observe-snapshot.EXAMPLE'
```

Undo verifies the snapshot, stops discovery and restores only the allowlisted
files, deleting only integration files that did not previously exist. It restores
the previous timer-enabled state and reloads Prometheus. Backups and retained
time-series data are not removed. Grafana eventually removes an unprovisioned
dashboard; restoring an older snapshot can overwrite newer changes to those
files, so inspect drift and select the right snapshot. `make observe` reapplies
the integration from the repository after undo.

An off-Pi baseline copy of the non-secret monitoring configuration was also
checked against the original SHA-256 values before installation. The original
dashboard, Compose, providers, rule files, Telegram configuration and Vaultwarden
backup/drill schedules were not changed.

## Verified result: 2026-09-27

Metrics release: `dca9cf84be9f35045f1bb91956762bd7ed0ca5fa`,
`ghcr.io/kernyx/pi-k3s-lab@sha256:7ae1b51a6ef272dbf62193210d0f8c35c2e4129687e9a72efeaa8377e5707358`.
[Successful CI run](https://github.com/Kernyx/pi-k3s-lab/actions/runs/36270675987).

| Target RPS | Workers | Seconds | Requests | Errors | Client p95 ms |
| --- | --- | --- | --- | --- | --- |
| 5 | 1 | 30.000 | 150 | 0 | 2.070 |
| 20 | 2 | 30.000 | 600 | 0 | 2.001 |
| 40 | 4 | 30.001 | 1200 | 0 | 1.913 |

- Both replicas participated in every phase: 1950 requests, zero errors total.
- Discovery replaced the two old pod addresses after a real registry rollout,
  without a manual Prometheus reload; both new targets became `up`.
- All eight dashboard PromQL expressions returned successful results. Grafana
  rendered 2 ready/2 scrapeable replicas and non-empty traffic/latency/RSS curves.
- In a post-test snapshot, pod request counters were 955 and 1002; histogram count
  was 1957, including the seven earlier business-route validation requests.
- Sampled process RSS maxima over the surrounding five-minute interval were
  24.59 and 24.63 MiB. These are 15-second-scraped samples, not proven true peaks
  or container-wide memory. `kubectl top` later showed 19 MiB per pod.
- Final snapshot: 2/2 Ready, zero pod restarts; nine previous host containers
  remained running, the two existing web services returned HTTP 200, both backup
  and drill timers remained enabled, and private link configuration hash matched.
- Prometheus/Grafana start timestamps and the k3s start time/restart count were
  unchanged. Existing Compose, provider and Vaultwarden dashboard hashes matched.
- Both automatic failure undo and a later explicit undo returned the original
  main-config hash and three existing jobs. Integration was then reinstalled.
- Raw load report/samples were copied to a private off-Pi directory; SHA-256
  matched both files. They and the screenshot are deliberately outside Git.

The reproducible monitoring code and checks are public; private host details,
personal portal links, kubeconfig, passwords and tokens are not.

## Limits and future improvements

- Monitoring and application share one Pi; neither is independent failure detection.
- The root discovery helper uses the admin kubeconfig. A dedicated read-only
  Kubernetes identity would reduce privilege in a larger deployment.
- A discovery API failure can leave stale targets. Check the timer/service result;
  there is no independent freshness alert for this helper yet.
- Reinstalling the first project's base monitoring configuration may remove the
  managed include: re-run `make observe`, which preserves the current base config.
- Undo is file-based, not a Grafana database or TSDB recovery test.
- Standard-library exposition is deliberately small and tested with `promtool`;
  a production app should normally use a maintained instrumentation library.

## Primary sources

- [Prometheus exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/)
- [Prometheus scrape config files and file discovery](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
- [Grafana file provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Actual false-negative activation incident](postmortems/004-external-scrape-config-check.md)
