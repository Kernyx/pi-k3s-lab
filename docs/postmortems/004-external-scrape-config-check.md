# False-negative monitoring activation check

## Incident: 2026-09-27

The first `make observe` installed a valid Prometheus scrape fragment, reloaded
Prometheus and then automatically reverted its own changes after ten seconds.
The monitoring service itself did not restart. Existing three jobs remained up;
the original configuration SHA-256 matched after rollback. Application delivery
was unaffected. No backup schedules or credentials were changed.

## Evidence and cause

- `promtool check config` accepted the candidate and all six existing rules.
- Prometheus logged successful configuration loads at 20:44:18 and 20:44:30 UTC
  (install and undo); neither load failed.
- The checker searched `/api/v1/status/config` for `job_name: home-portal`.
- Prometheus 3.14.0 serializes its main `Config` for this API. Jobs from
  `scrape_config_files` are loaded separately; the response preserves the
  include rather than expanding its jobs. The expected string cannot appear.
- The check was wrong, not the configuration or the HUP mechanism.

## Correction

Check both the active include in `/status/config` and the `home-portal` pool in
`/api/v1/scrape_pools`. Verify actual targets and ingested samples separately.
Regression tests cover the external-file response and removal of the pool on
undo. A valid syntax check alone does not establish successful ingestion.

## Limits

This was a real implementation failure, not a simulated outage. It demonstrated
automatic file rollback but did not test loss of the Pi or Grafana database
recovery. Saved files and original hashes remain in private backups.

## Primary sources

- [Prometheus 3.14.0 API implementation](https://github.com/prometheus/prometheus/blob/v3.14.0/web/api/v1/api.go)
- [Prometheus 3.14.0 config loading and serialization](https://github.com/prometheus/prometheus/blob/v3.14.0/config/config.go)
