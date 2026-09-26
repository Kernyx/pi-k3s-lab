#!/usr/bin/env python3
"""Finite rolling-update/readiness/rollback exercise on this lab's portal only."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen
import uuid

from app_state import CONFIG, RELEASE, app_lock, kubectl, owned_deployment, resource, restore, snapshot


def http(url):
    try:
        with urlopen(url, timeout=2) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, None


def summarize(samples):
    latencies = sorted(s['latency_ms'] for s in samples)
    successful = [s for s in samples if s['status'] == 200]
    return {'requests': len(samples), 'errors': len(samples) - len(successful),
            'latency_p95_ms': round(latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)], 3) if latencies else None,
            'instances': sorted({s['instance'] for s in successful if s.get('instance')}),
            'versions': sorted({s['version'] for s in successful if s.get('version')})}


class Sampler:
    def __init__(self, base, directory):
        self.base, self.directory = base, directory
        self.phase = 'baseline'
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run)

    def run(self):
        # Sequential, fresh TCP connections, ~10 requests/s total; no retries.
        opener_paths = ['/api/info', '/readyz']
        with (self.directory / 'requests.jsonl').open('w') as output:
            while not self.stop.is_set():
                for path in opener_paths:
                    started = time.monotonic()
                    sample = {'phase': self.phase, 'path': path, 'status': 0}
                    try:
                        status, body = http(self.base + path)
                        sample['status'] = status
                        if path == '/api/info' and body:
                            sample.update(instance=body['instance'], version=body['version'])
                    except Exception as error:
                        sample['status'] = 0
                        sample['error'] = type(error).__name__  # Never log private URL/body.
                    sample['latency_ms'] = round((time.monotonic() - started) * 1000, 3)
                    self.samples.append(sample)
                    output.write(json.dumps(sample) + '\n')
                    output.flush()
                self.stop.wait(0.2)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            raise RuntimeError('HTTP sampler failed to stop')


def wait_for(predicate, timeout, description):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError(description)


def active_pods():
    return [p for p in json.loads(kubectl('get', 'pods', '-l', 'app=home-portal', '-o', 'json'))['items']
            if not p['metadata'].get('deletionTimestamp')]


def broken_evidence(config_name):
    bad = [p for p in active_pods() if p['spec']['volumes'][0]['configMap']['name'] == config_name]
    if len(bad) != 1 or not bad[0]['status'].get('podIP'):
        return None
    pod = bad[0]
    containers = pod['status'].get('containerStatuses', [])
    if not containers or not containers[0].get('started'):
        return None
    base = f"http://{pod['status']['podIP']}:8080"
    health, _ = http(base + '/healthz')
    ready, _ = http(base + '/readyz')
    if health != 200 or ready != 503 or containers[0]['ready']:
        return None
    endpoints = json.loads(kubectl('get', 'endpointslices', '-l', 'kubernetes.io/service-name=home-portal', '-o', 'json'))
    serving = [e['targetRef']['name'] for s in endpoints['items'] for e in s.get('endpoints', [])
               if e.get('conditions', {}).get('ready') is True]
    good = [p for p in active_pods() if p['metadata']['name'] in serving]
    if pod['metadata']['name'] in serving or len(good) != 2:
        raise RuntimeError('Service did not isolate the unready replica')
    return {'name': pod['metadata']['name'], 'uid': pod['metadata']['uid'], 'health_status': health,
            'ready_status': ready, 'restarts': containers[0]['restartCount'], 'serving_instances': sorted(serving)}


def main():
    def interrupted(*_):
        raise KeyboardInterrupt('Interrupted drill; restoring the saved template')
    signal.signal(signal.SIGTERM, interrupted)
    with app_lock():
        deployment = owned_deployment(resource('deployment', 'home-portal'))
        if (deployment['spec']['replicas'] != 2 or deployment['status'].get('availableReplicas') != 2
                or deployment['status'].get('updatedReplicas') != 2):
            raise ValueError('Start from a healthy two-replica Deployment')
        if deployment['spec']['strategy']['rollingUpdate'] != {'maxSurge': 1, 'maxUnavailable': 0}:
            raise ValueError('Expected maxSurge=1 and maxUnavailable=0')
        if not RELEASE.exists():
            raise ValueError('Select a registry release before this drill')
        before = snapshot()
        directory = before / 'drill'
        directory.mkdir(mode=0o700)
        config_hash = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
        release_hash = hashlib.sha256(RELEASE.read_bytes()).hexdigest()
        service = resource('service', 'home-portal')
        sampler = Sampler(f"http://{service['spec']['clusterIP']}", directory)
        run_id = uuid.uuid4().hex[:12]
        config_name = 'home-portal-drill-' + run_id
        report = {'started_at': datetime.now(timezone.utc).isoformat(),
                  'source_revision': json.loads(RELEASE.read_text())['revision'], 'scenario': 'same-image template rollout and invalid-config rollout',
                  'pass': False}
        dirty = False
        failure = None
        sampler.thread.start()
        try:
            time.sleep(3)
            original_uids = {p['metadata']['uid'] for p in active_pods()}
            sampler.phase = 'healthy_rollout'
            healthy = copy.deepcopy(deployment['spec'])
            healthy['template']['metadata'].setdefault('annotations', {})['pi-k3s-lab/rollout-drill'] = run_id
            dirty = True  # Set before submitting: a lost API response may still mean success.
            started = time.monotonic()
            kubectl('patch', 'deployment', 'home-portal', '--type=merge', '-p', json.dumps({'spec': healthy}))
            kubectl('rollout', 'status', 'deployment/home-portal', '--timeout=180s')
            report['healthy_rollout_seconds'] = round(time.monotonic() - started, 3)
            if original_uids & {p['metadata']['uid'] for p in active_pods()}:
                raise RuntimeError('Healthy rollout did not replace both replicas')
            print(f"Healthy template rollout: {report['healthy_rollout_seconds']}s", flush=True)
            time.sleep(3)
            # Snapshot the stable post-rollout revision before injecting the failure.
            healthy_snapshot = snapshot()
            report['rollback_snapshot'] = healthy_snapshot.name
            cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': config_name, 'namespace': 'homelab',
                  'labels': {'app.kubernetes.io/part-of': 'pi-k3s-lab', 'pi-k3s-lab/drill': run_id}},
                  'immutable': True, 'data': {'links.json': '{"title":"","links":[]}'}}
            kubectl('create', '-f', '-', data=cm)
            failed = copy.deepcopy(healthy)
            failed['template']['spec']['volumes'][0]['configMap']['name'] = config_name
            failed['progressDeadlineSeconds'] = 30
            sampler.phase = 'failed_rollout'
            started = time.monotonic()
            kubectl('patch', 'deployment', 'home-portal', '--type=merge', '-p', json.dumps({'spec': failed}))
            report['failed_pod'] = wait_for(lambda: broken_evidence(config_name), 45, 'Broken replica did not become alive but unready')
            def deadline_exceeded():
                d = resource('deployment', 'home-portal')
                return any(c.get('type') == 'Progressing' and c.get('status') == 'False'
                           and c.get('reason') == 'ProgressDeadlineExceeded' for c in d['status'].get('conditions', []))
            wait_for(deadline_exceeded, 65, 'Deployment did not report ProgressDeadlineExceeded')
            report['failure_detection_seconds'] = round(time.monotonic() - started, 3)
            latest = broken_evidence(config_name)
            if latest is None or latest['uid'] != report['failed_pod']['uid'] or latest['restarts'] != 0:
                raise RuntimeError('Broken pod was restarted, replaced, or unexpectedly became ready')
            report['failed_pod'] = latest
            print(f"Readiness blocked rollout after {report['failure_detection_seconds']}s; old replicas still serve", flush=True)
            sampler.phase = 'rollback'
            started = time.monotonic()
            # Restore the exact healthy snapshot, not an ambiguous 'previous' revision.
            restore(healthy_snapshot)
            wait_for(lambda: len(active_pods()) == 2, 30, 'Broken surge pod was not removed')
            report['rollback_seconds'] = round(time.monotonic() - started, 3)
            print(f"Verified rollback: {report['rollback_seconds']}s", flush=True)
        except BaseException as error:
            report['exception'] = type(error).__name__
            failure = error
        finally:
            try:
                if dirty:
                    sampler.phase = 'cleanup'
                    # Also remove the harmless drill annotation and reset the 180s deadline.
                    restore(before)
                    wait_for(lambda: len(active_pods()) == 2, 30, 'Cleanup did not converge to two replicas')
                sampler.phase = 'recovered'
                time.sleep(3)
            except BaseException as error:
                report['cleanup_exception'] = type(error).__name__
                failure = error
            finally:
                sampler.finish()
            # Keep the exact owned test CM for diagnosis; no automatic broad pruning.
            report['temporary_configmap'] = config_name
            report['http'] = summarize(sampler.samples)
            report['phases'] = {phase: summarize([s for s in sampler.samples if s['phase'] == phase])
                                for phase in sorted({s['phase'] for s in sampler.samples})}
            report['private_config_unchanged'] = hashlib.sha256(CONFIG.read_bytes()).hexdigest() == config_hash
            report['selected_release_unchanged'] = hashlib.sha256(RELEASE.read_bytes()).hexdigest() == release_hash
            report['pass'] = (all(k in report for k in ['healthy_rollout_seconds', 'failed_pod', 'rollback_seconds'])
                              and report['http']['errors'] == 0 and report['private_config_unchanged']
                              and report['selected_release_unchanged']
                              and report['http']['versions'] == [report['source_revision']]
                              and report.get('failed_pod', {}).get('name') not in report['phases'].get('failed_rollout', {}).get('instances', [])
                              and 'exception' not in report and 'cleanup_exception' not in report)
            (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2), flush=True)
            print(f'Private evidence directory: {directory}', flush=True)
        if failure is not None:
            raise failure
        if not report['pass']:
            raise RuntimeError('Drill did not pass; inspect report and recovered state')


if __name__ == '__main__':
    main()
