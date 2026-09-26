# Stage 3: native ARM64 CI and digest-based delivery

## Delivery boundaries

GitHub Actions runs unit tests and ShellCheck first. Only a successful push to
`main` publishes an image; pull requests receive read-only checks. The build runs
on `ubuntu-24.04-arm`, without QEMU. The base Python image and every Action are
pinned by digest/commit. Only the publication job has `packages: write`; it uses
the ephemeral `GITHUB_TOKEN`, not a personal token or a host credential.

The image is published as `ghcr.io/<owner>/pi-k3s-lab:sha-<full-commit>`.
Its OCI source/revision labels and `APP_VERSION` identify the source commit.
The `home-portal-release` artifact contains only `image` (with SHA-256 digest)
and `revision`. BuildKit provenance may produce an OCI index even for one target
architecture; the deployment pins that index and containerd selects its ARM64
manifest. Neither a mutable tag nor a Docker image config ID is a substitute.

`make release SSH_HOST=my-pi RUN_ID=<successful-run>` downloads the artifact from
this repository and checks its commit against the successful main-branch push.
Alternatively, an operator can explicitly select `RELEASE_FILE=/path/release.json`.
The latter trusts that operator-supplied descriptor, not an Actions run.

On the Pi, deployment pulls anonymously into k3s containerd and checks ARM64/Linux,
the digest, source/revision labels and application version **before changing live
resources**. A SHA-256-verified snapshot retains the previous Deployment, Service,
private links and (when present) selected release. Probes and rolling update gate
readiness. HTTP checks then confirm the actual version of both active replicas.
Only after these checks does the script persist the selected release under
`/var/lib/pi-k3s-lab/deployed-release.json`. Future `make up`/`make deploy` reuse it;
they do not silently replace it with a local bootstrap build.

## Privacy and honest limitations

- GitHub documents private visibility as the default for first publication.
  Inspect the actual package: this run showed Public immediately and anonymous
  pull succeeded, so no visibility setting was changed. If private in another
  account, its owner must make this public-code-only package public once.
- Private link configuration remains outside Git, image layers and CI artifacts.
  The runner receives neither SSH access to the home network nor kubeconfig.
- Delivery has an explicit operator approval boundary: publication is automatic,
  installation is a command over the existing SSH connection. This is CI with
  controlled deployment, not autonomous GitOps.
- Digest pinning protects byte identity; labels are consistency checks, **not**
  cryptographic proof of publisher identity. Signature verification is not added.
- A failed pull/metadata check leaves Kubernetes resources alone. A failure after
  resource application is reported, not automatically rolled back; the next
  stage will exercise a deliberately broken rollout and measured recovery.
- Artifact retention is 30 days. Keep a selected public `release.json` outside
  Git for later reuse. Old images/config maps/snapshots are retained for rollback;
  cleanup and microSD write budgets remain future work.

## Verification

Live snapshot: 2026-09-27, first registry release, commit
`dd554fe1177ef8d8bbed0331372e3af96f1f9b7c`.

| Check | Observed result |
| --- | --- |
| Tests and Bash lint | 18 unit tests and ShellCheck passed locally/on Pi/in Actions |
| CI | [Run 36267956220](https://github.com/Kernyx/pi-k3s-lab/actions/runs/36267956220): both jobs successful |
| ARM64 publication | OCI index `sha256:73a3248246340db9040a0e69f72ec136978a629fe8037b17135d40b7bc9feb67` |
| ARM64 child manifest | `sha256:71e040212ade0fa5df0994f7ba269fa942151d32328d8e1b08d37644ce912b5f` |
| Download/provenance checks | Anonymous `crictl pull`; Linux/ARM64, digest, labels and APP_VERSION matched |
| Deployment | 2/2 Ready, zero restarts, `IfNotPresent`, digest pinned in spec and runtime imageID |
| Application | Seven HTTP routes through Service; both pod IPs returned the full release commit |
| Idempotence | Integrated `make up`: same two pod UIDs, unchanged resources, k3s original start unchanged |
| Private configuration | Original SHA-256 and immutable ConfigMap remained unchanged |
| Adjacent services | All nine Docker/Podman containers remained up; news aggregator, feed reader and Grafana HTTP 200 |
| Memory snapshot | Portal pods 16/17 MiB, approximately 1m CPU each without load |
| Tunnel lifecycle | Portal + Grafana HTTP 200; Ctrl+C freed remote/local ports; reopening succeeded |

The pre-release snapshot passed SHA-256 verification on Pi and after copying to
private off-Pi storage. The public release descriptor was also retained outside
the repository. This is a successful delivery/idempotence test, not an outage
benchmark or the intentionally failed-release/rollback drill of stage 4.
The tunnel incident and fix are recorded in
[postmortem 002](postmortems/002-orphaned-port-forward.md).

## Interview question

Why does a `sha-<commit>` tag not guarantee that two installations run the same
image, and what does pinning an image digest guarantee instead?

## Primary references

- [GitHub-hosted ARM runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GHCR tokens, visibility and digest pulls](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Docker build-push Action](https://github.com/docker/build-push-action)
- [Kubernetes image pull policy](https://kubernetes.io/docs/concepts/containers/images/)
