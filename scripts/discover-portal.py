#!/usr/bin/env python3
"""Export only this Service's ready pod endpoints to Prometheus file discovery."""

import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile

TARGET = Path('/opt/vaultwarden-restore-drill/monitoring/prometheus/pi-k3s-lab/targets.json')


def targets(document):
    found = {}
    for item in document['items']:
        if (item['metadata'].get('labels', {}).get('kubernetes.io/service-name') != 'home-portal'
                or item['metadata'].get('namespace') != 'homelab'):
            raise ValueError('Unexpected EndpointSlice owner')
        ports = [p['port'] for p in item['ports'] if p.get('name') == 'http' and p.get('protocol') == 'TCP']
        if ports != [8080]:
            raise ValueError('Unexpected portal port')
        for endpoint in item['endpoints']:
            conditions, ref = endpoint.get('conditions', {}), endpoint.get('targetRef', {})
            if not conditions.get('ready') or conditions.get('terminating'):
                continue
            if ref.get('kind') != 'Pod' or ref.get('namespace') != 'homelab':
                raise ValueError('Not a homelab pod')
            for address in endpoint['addresses']:
                ip = ipaddress.ip_address(address)
                if ip not in ipaddress.ip_network('10.42.0.0/16'):
                    raise ValueError('Endpoint outside the lab pod network')
                found[ref['name']] = {'targets': [f'{ip}:8080'],
                                      'labels': {'instance': ref['name'], 'pod': ref['name'], 'namespace': 'homelab'}}
    return [found[key] for key in sorted(found)]


def atomic_write(path, content, mode=0o644):
    if path.exists() and path.read_bytes() == content and path.stat().st_mode & 0o777 == mode:
        return
    fd, name = tempfile.mkstemp(prefix='.pi-k3s-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    # Failure preserves the last good file; successful discovery of zero ready pods writes [].
    result = subprocess.run(['/usr/local/bin/k3s', 'kubectl', '--request-timeout=10s', '-n', 'homelab',
                             'get', 'endpointslices', '-l', 'kubernetes.io/service-name=home-portal', '-o', 'json'],
                            text=True, capture_output=True, check=True, timeout=15)
    content = (json.dumps(targets(json.loads(result.stdout)), indent=2) + '\n').encode()
    atomic_write(TARGET, content)


if __name__ == '__main__':
    main()
