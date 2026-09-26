# Stage 2: a useful application in Kubernetes

Verified on 2026-09-27, local time UTC+05, on the existing ARM64 Raspberry Pi.

## Application and access

The home portal lists configured services and documentation, with client-side search.
The application uses Python's standard library and static HTML/CSS/JavaScript.
It does not check the health of linked services and displays no invented health status.
The browser opens links; the server does not fetch arbitrary configured URLs.

`make open SSH_HOST=my-pi` creates localhost SSH tunnels to the portal and existing
Grafana. Kubernetes port-forward selects one backing pod. It is a convenient access
path, **not a load-balancing test**. The separate app check uses the ClusterIP Service.

## Components to explain

| Component | Responsibility |
| --- | --- |
| Dockerfile | Pinned Python base, application source, version environment, UID/GID 65532. |
| Native Docker build | Build on ARM64 without cross-architecture emulation. |
| `docker save` / `k3s ctr images import` | Move the image between independent Docker and k3s containerd stores. |
| Deployment | Maintain two replicas, own the pod template and rolling-update policy. |
| Immutable ConfigMap | Supply personal links; content hash in the name identifies each config version. |
| ClusterIP Service | Stable internal address and selector for the Ready pods. |
| `source-version.py` | Hash only the public files used to build the image, independent of private links. |

Both replicas run on one Pi. They prepare the lab for rolling updates; a Pi outage
still stops the whole application. Release testing and registry delivery are later stages.

## Health and resource policy

`/healthz` proves the HTTP process can answer. `/readyz` additionally requires a valid
links configuration. Startup probe gives the process time to start; readiness decides
whether Service traffic should reach a pod; repeated liveness failures cause a restart.
An invalid JSON configuration produces readiness 503 with liveness 200, verified by tests.
The configuration is read at startup. Changes deploy a new immutable ConfigMap and new pods.

Per pod: CPU request 10m, limit 250m; memory request 32 MiB, limit 64 MiB.
Requests affect scheduling; limits are enforced at runtime. Startup probe allows
30 attempts at two-second intervals; readiness checks every five seconds; liveness
checks every ten seconds and tolerates three failures.

## Live evidence

- Deployment: 2/2 Ready, zero container restarts.
- Seven HTTP routes returned success through ClusterIP: page, CSS, JS, health,
  readiness, config API and version API.
- 30 independent connections to `/api/info` through Service reached both replicas:
  18 responses from one, 12 from the other. All reported `src-65ac0ce8498f`.
- RAM snapshot without a load test: **16 MiB and 18 MiB**; CPU **1m per pod**.
- Both containers reported UID 65532, `memory.max=67108864`, `memory.swap.max=0`,
  `cpu.max=25000 100000`, read-only root filesystem, no service-account token.
- Image build reported ARM64, uncompressed Docker image size 143425883 bytes (~137 MiB).
- Browser rendered five configured links. Searching `Grafana` showed one card;
  clearing the query restored all five.
- Existing newsrank/Miniflux HTTP endpoints and the Grafana tunnel responded successfully.
- Existing Prometheus and Grafana health endpoints stayed HTTP 200 during the build.
- Twelve unit tests passed locally and on the Pi; Bash syntax and ShellCheck passed.
- Repeated `make up`: Deployment, Service and ConfigMap unchanged; the two pod UIDs
  and restart counts stayed the same. k3s retained its original start time.

These measurements are snapshots, not throughput or availability guarantees.
The portal uses Python `http.server`, which is a teaching choice for private access,
not a claim of production hardening.

## Privacy and rollback preparation

The public example contains documentation links only. Personal URLs remain in a private
file outside Git, a root-readable file on the Pi, its restricted snapshot directories
and the cluster ConfigMap. They are absent from the application image and public source.
ConfigMap contents are not secret storage; do not put credentials in link URLs.

Before applying an app change, Deployment/Service and current links are saved and
SHA-256 checked. Prior immutable ConfigMaps remain available for later rollout undo.
First deployment has no earlier application revision. A real failed-release/rollback
drill has not yet been performed.

## Interview question

**What happens when readiness fails but liveness still passes? Why should a bad
configuration not automatically cause an endless restart loop?**

References: [probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/),
[ConfigMaps](https://kubernetes.io/docs/concepts/configuration/configmap/),
[security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/),
[Python HTTP server](https://docs.python.org/3.13/library/http.server.html).
