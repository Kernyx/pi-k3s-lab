#!/usr/bin/env python3
"""Extend the existing localhost monitoring with a sealed backup and explicit undo."""

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

spec = importlib.util.spec_from_file_location('discovery', Path(__file__).with_name('discover-portal.py'))
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)
from dashboard import dashboard

BASE = Path('/opt/vaultwarden-restore-drill/monitoring')
STATE = Path('/var/lib/pi-k3s-lab')
PROMETHEUS = 'vw-monitoring-prometheus-1'
UNIT = 'pi-k3s-portal-discovery.timer'
PROM = BASE / 'prometheus/prometheus.yml'
FRAGMENT = BASE / 'prometheus/pi-k3s-lab/home-portal.yml'
SCRIPT = Path('/opt/pi-k3s-lab/monitoring/discover-portal.py')
OBSERVER = SCRIPT.with_name('observe.py')
DASHBOARD_SCRIPT = SCRIPT.with_name('dashboard.py')
DASHBOARD = BASE / 'grafana/dashboards/pi-k3s-home-portal.json'
SERVICE = Path('/etc/systemd/system/pi-k3s-portal-discovery.service')
TIMER = Path('/etc/systemd/system') / UNIT
FILES = [PROM, FRAGMENT, SCRIPT, OBSERVER, DASHBOARD_SCRIPT, DASHBOARD, SERVICE, TIMER, discovery.TARGET]
INCLUDE = '\n# pi-k3s-lab managed include\nscrape_config_files:\n  - /etc/prometheus/pi-k3s-lab/home-portal.yml\n'


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True, timeout=30).stdout


def backup():
    directory = Path(tempfile.mkdtemp(prefix='observe-snapshot.', dir=STATE))
    manifest = {}
    for i, path in enumerate(FILES):
        if path.is_symlink():
            raise ValueError('Refusing symlink: ' + str(path))
        if path.exists():
            content, stat = path.read_bytes(), path.stat()
            saved = directory / str(i)
            saved.write_bytes(content)
            saved.chmod(0o600)
            manifest[str(path)] = {'file': str(i), 'sha256': hashlib.sha256(content).hexdigest(),
                                   'mode': stat.st_mode & 0o777, 'uid': stat.st_uid, 'gid': stat.st_gid}
        else:
            manifest[str(path)] = None
    enabled = subprocess.run(['systemctl', 'is-enabled', UNIT], capture_output=True, text=True).stdout.strip() == 'enabled'
    (directory / 'manifest.json').write_text(json.dumps({'files': manifest, 'timer_enabled': enabled}, indent=2) + '\n')
    (directory / 'manifest.json').chmod(0o600)
    seal = hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest()
    (directory / 'manifest.sha256').write_text(seal + '\n')
    (directory / 'manifest.sha256').chmod(0o600)
    verify(directory)
    print('Verified monitoring backup:', directory, flush=True)
    return directory


def verify(directory):
    if (directory.is_symlink() or directory.resolve().parent != STATE or not directory.name.startswith('observe-snapshot.')
            or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o022):
        raise ValueError('Select a root-owned observe-snapshot under the lab state directory')
    content = (directory / 'manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != (directory / 'manifest.sha256').read_text().strip():
        raise ValueError('Backup manifest checksum mismatch')
    manifest = json.loads(content)
    if set(manifest['files']) != {str(p) for p in FILES}:
        raise ValueError('Backup inventory mismatch')
    for entry in manifest['files'].values():
        if entry is not None:
            name = entry['file']
            if name not in {str(i) for i in range(len(FILES))} or (directory / name).is_symlink():
                raise ValueError('Invalid saved file')
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Saved file checksum mismatch')
    return manifest


def restore(directory):
    manifest = verify(directory)
    if TIMER.exists():
        run('systemctl', 'disable', '--now', UNIT)
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE.name]).returncode == 0:
        run('systemctl', 'stop', SERVICE.name)
    # Exact allowlisted files, never a recursive removal; backups remain intact.
    for path in FILES:
        entry = manifest['files'][str(path)]
        if path.is_symlink():
            raise ValueError('Refusing changed symlink: ' + str(path))
        if entry is None:
            path.unlink(missing_ok=True)
        else:
            discovery.atomic_write(path, (directory / entry['file']).read_bytes(), entry['mode'])
            os.chown(path, entry['uid'], entry['gid'])
    run('systemctl', 'daemon-reload')
    if manifest['timer_enabled']:
        run('systemctl', 'enable', '--now', UNIT)
    run('docker', 'exec', PROMETHEUS, 'promtool', 'check', 'config', '/etc/prometheus/prometheus.yml')
    run('docker', 'kill', '--signal=HUP', PROMETHEUS)
    wait_reload('home-portal' in (directory / manifest['files'][str(PROM)]['file']).read_text())
    print('Restored monitoring files; existing Vaultwarden jobs preserved.', flush=True)


def wait_reload(expect_portal):
    for _ in range(20):
        with urllib.request.urlopen('http://127.0.0.1:9090/api/v1/status/config', timeout=3) as response:
            active = json.load(response)['data']['yaml']
        if ('job_name: home-portal' in active) == expect_portal:
            return
        time.sleep(0.5)
    raise RuntimeError('Prometheus did not activate the intended scrape configuration')


def install():
    mounts = json.loads(run('docker', 'inspect', '--format', '{{json .Mounts}}', PROMETHEUS))
    if not any(m['Source'] == str(BASE / 'prometheus') and m['Destination'] == '/etc/prometheus' for m in mounts):
        raise ValueError('Expected directory bind mount for the existing monitoring')
    original = PROM.read_text()
    if INCLUDE not in original and 'scrape_config_files:' in original:
        raise ValueError('Existing scrape_config_files needs manual merge; not overwritten')
    if 'job_name: home-portal' in original:
        raise ValueError('A portal scrape job already exists in the main config')
    source = Path(__file__).resolve().parents[1]
    intended = {FRAGMENT: (source / 'monitoring/home-portal.yml').read_bytes(),
                SCRIPT: Path(__file__).with_name('discover-portal.py').read_bytes(),
                OBSERVER: Path(__file__).read_bytes(),
                DASHBOARD_SCRIPT: Path(__file__).with_name('dashboard.py').read_bytes(),
                DASHBOARD: (json.dumps(dashboard(), indent=2) + '\n').encode(),
                SERVICE: (source / 'monitoring' / SERVICE.name).read_bytes(),
                TIMER: (source / 'monitoring' / TIMER.name).read_bytes()}
    # Don't overwrite someone else's integration under our names.
    for path in intended:
        if path.exists() and INCLUDE not in original:
            raise ValueError('Existing integration files without managed include; inspect first')
    # Refuse a metrics-less old release before changing the monitoring.
    endpoints = json.loads(run('/usr/local/bin/k3s', 'kubectl', '--request-timeout=10s', '-n', 'homelab',
                               'get', 'endpointslices', '-l', 'kubernetes.io/service-name=home-portal', '-o', 'json'))
    ready = discovery.targets(endpoints)
    if len(ready) != 2:
        raise ValueError('Expected two ready portal endpoints')
    for target in ready:
        with urllib.request.urlopen('http://' + target['targets'][0] + '/metrics', timeout=3) as response:
            if b'portal_ready 1\n' not in response.read(65536):
                raise ValueError('Deploy the metrics-capable release before installing monitoring')
    directory = backup()
    try:
        for path, content in intended.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            discovery.atomic_write(path, content)
        discovery.main()
        candidate = BASE / 'prometheus/.pi-k3s-candidate.yml'
        discovery.atomic_write(candidate, (original if INCLUDE in original else original + INCLUDE).encode())
        try:
            print(run('docker', 'exec', PROMETHEUS, 'promtool', 'check', 'config', '/etc/prometheus/.pi-k3s-candidate.yml'), end='')
            stat = PROM.stat()
            discovery.atomic_write(PROM, candidate.read_bytes(), stat.st_mode & 0o777)
            os.chown(PROM, stat.st_uid, stat.st_gid)
        finally:
            candidate.unlink(missing_ok=True)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', '--now', UNIT)
        run('systemctl', 'start', SERVICE.name)
        run('docker', 'kill', '--signal=HUP', PROMETHEUS)
        wait_reload(True)
        with urllib.request.urlopen('http://127.0.0.1:9090/-/ready', timeout=3) as response:
            if response.status != 200:
                raise RuntimeError('Prometheus not ready after reload')
    except Exception:
        restore(directory)
        raise
    print('Installed portal discovery, scrape config and dashboard. Undo with:', flush=True)
    print(f'python3 {OBSERVER} --restore {directory}', flush=True)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run as root on the Pi')
    with open('/run/lock/pi-k3s-lab-observe.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if len(sys.argv) == 3 and sys.argv[1] == '--restore':
            restore(Path(sys.argv[2]))
        elif len(sys.argv) == 1:
            install()
        else:
            raise ValueError('Usage: observe.py [--restore /var/lib/pi-k3s-lab/observe-snapshot.NAME]')


if __name__ == '__main__':
    main()
