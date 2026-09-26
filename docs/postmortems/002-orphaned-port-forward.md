# 002: closing SSH left a remote port-forward listening

Date: 2026-09-27. Scope: private portal access tunnel, not the application pods.

## Impact and detection

Following the first registry rollout, the portal's two replicas were healthy.
The operator closed the old `make open` session with Ctrl+C and tried to reopen
it. The local SSH forwards had closed, but the remote command failed:
`Unable to listen on port 18080: ... bind: address already in use`.
Browser access through that tunnel was unavailable; the internal ClusterIP and
adjacent home services continued to work. No downtime figure was measured.

## Evidence and cause

`ss -ltnp` on the Pi showed a root-owned kubectl client listening on localhost
18080. Its parent was the old `sudo -n k3s kubectl -n homelab port-forward ...`
process with parent PID 1. Standard input/output/error still pointed to pipes.
The original SSH command had no remote PTY: disconnecting the local session did
not terminate that sudo/client process in this observed run. The next tunnel
could bind its local port but could not create a new remote listener.

## Remediation

1. Inspect the listener PID, parent command and file descriptors; verify it is
   this lab's old client, **not** the k3s server or someone else's forwarding job.
2. Send SIGTERM to that specific client only. Confirm the remote port is free.
3. Add `ssh -tt` to `make open` so the remote command has a terminal. Ctrl+C is
   delivered to the foreground command; disconnect gets terminal hangup behavior.
   BatchMode, connection timeout and keepalives remain enabled.

## Verification

- Reopened the tunnel; portal `/api/info` returned the registry commit and the
  forwarded Grafana health endpoint returned HTTP 200.
- Closed this new session with Ctrl+C. `ss` confirmed no listeners on remote
  localhost 18080 or local localhost 18080/13000.
- Immediately reopened the same command successfully.
- Bash syntax and ShellCheck passed for the changed script.

## Limits and prevention

This tests ordinary Ctrl+C/disconnect, not every network partition or SIGKILL.
Keepalives bound detection of an unresponsive SSH connection. A port-forward is
still temporary and tied to one selected pod; reconnect after a rollout when
needed. Do not solve a stale client by killing all k3s/kubectl processes or
restarting the Pi. Remove the PTY option to revert the code change, but that
reintroduces the observed cleanup risk.
