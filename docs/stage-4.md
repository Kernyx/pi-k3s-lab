# Stage 4: rolling update, readiness failure and measured rollback

## Result: one real Pi exercise, 2026-09-27

The selected image remained the stage-3 release, Git revision
`bc5fd6ddfb5c3cc85bb9398470606d4b827b3f77`. The healthy rollout changed a pod-template
annotation, **not the image or application code**. This still replaced both
replicas through the Deployment's actual rolling-update controller. The failed
revision changed its immutable ConfigMap reference to a deliberately invalid
configuration. This tests Kubernetes' readiness boundary independently of the
normal CLI preflight, which would reject the same invalid configuration first.

| Measurement | Observed result |
| --- | --- |
| Healthy template rollout | 16.291 s |
| Failure detection | 30.818 s, `Progressing=False / ProgressDeadlineExceeded` |
| Broken surge pod | `/healthz` 200, `/readyz` 503, zero restarts |
| Service during failed rollout | Two healthy endpoints; broken pod excluded |
| Verified rollback | 2.461 s |
| Service HTTP requests across all phases | 746, **0 errors**, no retries |
| Client latency p95 across all phases | 1.977 ms |
| Original configuration / selected release | File hashes unchanged |
| Final Deployment | Exact original spec, 2/2 Ready, zero restarts, deadline 180 s |
| Subsequent `make up` | Resources unchanged, k3s not restarted |
| Adjacent host services | Nine containers still up; news aggregator, feed reader and Grafana HTTP 200 |

The rollback timer starts before the spec-restore API call and ends after rollout,
both replicas' actual version/image checks, seven routes through Service, pod
metrics and removal of the unready surge pod. The two good replicas never stopped
serving; **2.461 s is not recovery time from a whole-service outage**. Removing the
harmless test annotation afterwards caused another rolling update, also sampled.

The HTTP sampler runs on the Pi against the IPv4 ClusterIP, alternates `/api/info`
and `/readyz`, uses fresh connections, a 2 s timeout and a 0.2 s pause per pair
(target roughly 10 requests/s, sequential). It counts non-200, transport and invalid
response errors without retries. This is a low-rate continuity test, not a load
capacity test, external-user SLA, or proof of high availability.

| Phase | Requests | Errors | Client p95 (ms) |
| --- | ---: | ---: | ---: |
| Baseline | 32 | 0 | 1.672 |
| Healthy rollout | 196 | 0 | 1.802 |
| Failed rollout | 308 | 0 | 1.913 |
| Rollback | 24 | 0 | 2.352 |
| Cleanup rolling update | 156 | 0 | 2.456 |
| Recovered | 30 | 0 | 1.375 |

## Repeat the exercise

```sh
make drill SSH_HOST=my-pi
```

Prerequisites: this lab's healthy two-replica registry deployment, retained good
immutable ConfigMap, available CPU/memory for one surge pod and root `sudo -n`.
The shared deployment lock prevents overlapping lab operations. Before mutation,
the script saves root-private Deployment/Service JSON, link configuration and
selected release with SHA-256 checksums. It only targets `homelab/home-portal`.
The first baseline was also copied to private off-Pi storage and reverified.

The drill shortens `progressDeadlineSeconds` to 30 temporarily. Kubernetes reports
the stalled rollout; **Kubernetes does not automatically roll it back**. This
operator-invoked script selects an exact verified healthy snapshot, restores the
Deployment spec with a JSON Patch replacement, checks runtime versions and then
restores the original pre-drill spec in `finally`. Replacement matters: a merge
patch that simply omits a newly added annotation would leave that key behind.

Evidence is retained privately under the printed
`/var/lib/pi-k3s-lab/app-snapshot.<id>/drill/`: `report.json` and `requests.jsonl`.
Raw evidence was copied off Pi; SHA-256 matched at both ends. The public repo
contains only aggregate results, not Deployment snapshots or private links.

## Explicit rollback

```sh
make rollback SSH_HOST=my-pi SNAPSHOT_DIR=/var/lib/pi-k3s-lab/app-snapshot.EXAMPLE
```

Select a root-owned snapshot printed by this lab, not an inferred "previous"
revision. The command verifies checksum inventory, saved image/release identity,
ownership, a valid private links file, the retained immutable ConfigMap and an
unchanged Service spec. It saves current state first, restores the Deployment,
checks both replicas and Service, then activates the saved links/release files.
This prevents a later `make up` from redeploying a release that was rolled back.

The standalone command was exercised against the original healthy snapshot:
it reported no Deployment change and passed actual version/route checks. Existing
application deliveries now produce this rollback-compatible snapshot format;
the first-ever bootstrap has no previous Deployment. Old stage-2/3 YAML snapshots
remain diagnostic copies, not input to this new JSON snapshot command. Automated
rollback supports registry releases, not pre-registry bootstrap images.

## Limits

- This exercised configuration failure with the same image, not a database
  migration, a different faulty binary, a full Pi outage, or a missing old image.
- `finally` handles ordinary Python errors/interrupts, not SIGKILL, power loss or
  a disconnected control plane. Keep the printed recovery snapshot and SSH access.
- Normal deployment is still operator controlled. Its failure is reported;
  there is no always-on automatic rollback controller.
- Test ConfigMap and snapshots remain for diagnosis; no broad deletion/pruning
  is performed. The ConfigMap contains invalid example JSON, not private data.
- One node, microSD and no ingress mean no hardware/network HA is established.

## Interview question

The new pod is Running, liveness succeeds, but readiness fails. Why do users still
receive successful requests, why is the pod not restarted, and who rolls it back?

## Primary references

- [Deployment progress deadlines, rolling updates and rollback](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Readiness versus liveness](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [JSON Patch](https://datatracker.ietf.org/doc/html/rfc6902)
