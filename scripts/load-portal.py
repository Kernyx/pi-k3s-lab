#!/usr/bin/env python3
"""Bounded same-host Service test, not a saturation test or a production SLA."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.request import urlopen

from app_state import app_lock, owned_deployment, resource, RELEASE, STATE
from release import load_release


def summarize(samples, elapsed):
    latencies = sorted(row['latency_ms'] for row in samples)
    return {'requests': len(samples), 'errors': sum(not row['ok'] for row in samples),
            'elapsed_seconds': round(elapsed, 3), 'actual_rps': round(len(samples) / elapsed, 3),
            'client_p95_ms': round(latencies[math.ceil(len(latencies) * .95) - 1], 3) if latencies else None,
            'instances': sorted({row['instance'] for row in samples if row.get('instance')})}


def memory_available():
    line = next(line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    return int(line.split()[1]) * 1024


def phase(base, revision, duration, rps, concurrency):
    stop = threading.Event()
    started = time.monotonic()
    deadline = started + duration
    interval = concurrency / rps

    def worker(number):
        rows = []
        next_request = started + number / rps
        while not stop.is_set() and next_request < deadline:
            if stop.wait(max(0, next_request - time.monotonic())) or time.monotonic() >= deadline:
                break
            tick = time.monotonic()
            row = {'ok': False, 'instance': None}
            try:
                if memory_available() < 1024 ** 3:
                    raise RuntimeError('Available host memory below 1 GiB; stopping')
                # A fresh TCP connection per sample, no retries and no external URL input.
                with urlopen(base + '/api/info', timeout=2) as response:
                    data = json.loads(response.read(4096))
                    row.update(status=response.status, instance=data.get('instance'), version=data.get('version'))
                    row['ok'] = response.status == 200 and data.get('version') == revision and isinstance(data.get('instance'), str)
            except Exception as error:
                row['error'] = type(error).__name__
            row['latency_ms'] = (time.monotonic() - tick) * 1000
            rows.append(row)
            if not row['ok']:
                stop.set()
            # Skip missed slots rather than issuing a catch-up burst.
            next_request = max(next_request + interval, time.monotonic())
        return rows

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        groups = list(pool.map(worker, range(concurrency)))
    if not stop.is_set():
        stop.wait(max(0, deadline - time.monotonic()))
    samples = [row for group in groups for row in group]
    elapsed = time.monotonic() - started
    result = summarize(samples, elapsed)
    result.update(target_rps=rps, concurrency=concurrency, planned_seconds=duration)
    return result, samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=30, choices=range(5, 31), help='Seconds per phase, at most 30')
    args = parser.parse_args()
    os.umask(0o077)
    with app_lock():
        revision = load_release(RELEASE)['revision']
        checksum = hashlib.sha256(RELEASE.read_bytes()).hexdigest()
        if Path(str(RELEASE) + '.sha256').read_text().split()[0] != checksum:
            raise ValueError('Selected release checksum mismatch')
        deployment = owned_deployment(resource('deployment', 'home-portal'))
        if deployment['status'].get('readyReplicas') != 2:
            raise RuntimeError('Expected two ready replicas before this test')
        if deployment['spec']['template']['spec']['containers'][0]['image'] != load_release(RELEASE)['image']:
            raise ValueError('Deployment does not use the selected release')
        base = 'http://' + resource('service', 'home-portal')['spec']['clusterIP']
        directory = Path(tempfile.mkdtemp(prefix='load-test.', dir=STATE))
        report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'revision': revision,
                  'method': 'same-host ClusterIP, fresh TCP, /api/info, no retries', 'phases': []}
        failed = False
        with (directory / 'requests.jsonl').open('w') as raw:
            for rps, concurrency in ((5, 1), (20, 2), (40, 4)):
                result, samples = phase(base, revision, args.duration, rps, concurrency)
                report['phases'].append(result)
                for row in samples:
                    raw.write(json.dumps({'target_rps': rps, **row}) + '\n')
                raw.flush()
                (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
                print(json.dumps(result), flush=True)
                if result['errors'] or len(result['instances']) != 2:
                    failed = True
                    break
        for path in directory.iterdir():
            path.chmod(0o600)
        print('Private load evidence:', directory, flush=True)
        if failed:
            raise RuntimeError('Load test stopped: error or both replicas not observed')
        print('PASS: bounded three-phase test; this does not establish maximum capacity', flush=True)


if __name__ == '__main__':
    main()
