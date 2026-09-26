# 001: A mounted disk was not a healthy storage candidate

Date: 2026-09-26. Impact: blocked choosing the HDD for the new Kubernetes lab.
No cluster or production data had been placed on it; no formatting or destructive
surface test was performed.

## What happened

A USB HDD mounted successfully as ext4, with plenty of free space. That proved
the filesystem was accessible, not that all sectors could be read reliably.
The disk's aggregate SMART health reported success, but individual attributes
reported one pending sector and one offline-uncorrectable sector.

A short SMART self-test ended with `Completed: read failure`, at 90% remaining,
with a first failing LBA recorded. This was enough to reject the disk as a
Kubernetes state/data device. The historical CRC counter was also nonzero;
that alone does not establish a current cable fault.

## Evidence and uncertainty

- Read failure is confirmed by the drive's self-test log.
- The number of affected readable files was not established.
- A full surface test, cable comparison and drive repair were not performed.
- Successful mounting and aggregate SMART health did not contradict the more
  specific failure evidence.

## Decision

Leave the disk and existing filesystem untouched. Use the existing microSD only
for a small disposable single-node SQLite-backed lab, with explicit approval.
Do not present microSD as equivalent to reliable SSD storage. Do not migrate
existing valuable application data into the new cluster.

## Prevention

For future storage changes, check the mount, transport, SMART attributes and
self-test result **before** moving workloads. Choose a healthy replacement
before adding stateful services; verify backups and an actual restore separately.
