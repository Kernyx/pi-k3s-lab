# 003: an invalid configuration stalled a rollout

Date: 2026-09-27. **Controlled failure exercise**, not an unexpected production
incident. Scope: the portal Deployment only; no private links file was corrupted.

## Timeline and impact

1. Saved and integrity-checked the healthy state, including an off-Pi copy.
2. Recreated both replicas via a harmless template annotation: 16.291 s.
3. Pointed the next template at a separate immutable ConfigMap containing
   `{"title":"","links":[]}`. It bypassed the normal CLI configuration preflight
   deliberately, to exercise the Kubernetes safety boundary.
4. The surge pod ran but returned readiness 503, liveness 200 and had zero restarts.
   The Service continued using two healthy pods; the broken pod was excluded.
5. After 30.818 s, the Deployment reported `ProgressDeadlineExceeded` (temporary
   deadline 30 s). The script explicitly restored the exact healthy snapshot.
6. Rollback and runtime checks completed in 2.461 s. The original pre-drill spec
   and 180 s deadline were restored, and normal `make up` remained idempotent.

746 sampled HTTP requests had zero errors, including failed-rollout, rollback and
cleanup phases. This did not create a measured whole-service outage. See the
[measurement method and phase counts](../stage-4.md).

## Cause and contributing design

The JSON parsed but violated the portal's configuration schema. The process could
run and answer liveness; it could not serve valid configured links. Readiness
therefore blocked service membership. `maxUnavailable=0 / maxSurge=1` kept both
working replicas while admitting only one not-ready candidate. A deadline reports
failure; it does not create an automatic rollback policy.

## Resolution and prevention

- Restore the exact verified Deployment spec and immutable ConfigMap reference,
  not a moving `previous` revision.
- Check the actual version of both replicas and HTTP through Service, not just
  `kubectl` exit status. Keep persisted release/config selection consistent.
- Keep CLI configuration validation, probes and snapshot checks as separate layers.
- Do not replace readiness with liveness or restart a process repeatedly for a
  configuration error; correct the configuration or roll back the template.

## What remains untested

Different broken image versions, migrations, saturation, host failures, endpoint
propagation under heavy traffic and external ingress. The raw report/requests and
root-private snapshots are retained outside Git for follow-up investigation.
