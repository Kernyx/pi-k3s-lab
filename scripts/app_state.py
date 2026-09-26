#!/usr/bin/env python3
"""Private, integrity-checked snapshots and explicit portal rollback."""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from release import load_release

STATE = Path('/var/lib/pi-k3s-lab')
CONFIG = Path('/etc/pi-k3s-lab/links.json')
RELEASE = STATE / 'deployed-release.json'
KUBECTL = ['/usr/local/bin/k3s', 'kubectl', '--request-timeout=15s', '-n', 'homelab']


def kubectl(*args, data=None):
    return subprocess.run(KUBECTL + list(args), input=json.dumps(data) if data is not None else None,
                          text=True, capture_output=True, check=True, timeout=200).stdout


def resource(kind, name):
    return json.loads(kubectl('get', kind, name, '-o', 'json'))


@contextlib.contextmanager
def app_lock():
    if os.geteuid() != 0:
        raise RuntimeError('Run as root on the Pi')
    with open('/run/lock/pi-k3s-lab-app.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def owned_deployment(deployment):
    metadata = deployment['metadata']
    if (metadata.get('name') != 'home-portal' or metadata.get('namespace') != 'homelab'
            or metadata.get('labels', {}).get('app.kubernetes.io/part-of') != 'pi-k3s-lab'):
        raise ValueError('Not this lab\'s portal Deployment')
    return deployment


def seal(directory):
    checks = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(directory.iterdir()) if p.is_file() and p.name != 'checksums.json'}
    (directory / 'checksums.json').write_text(json.dumps(checks, indent=2) + '\n')
    verify(directory)


def verify(directory):
    checks = json.loads((directory / 'checksums.json').read_text())
    actual = {p.name for p in directory.iterdir() if p.is_file() and p.name != 'checksums.json'}
    if actual != set(checks):
        raise ValueError('Snapshot file inventory differs from its checksum manifest')
    for name, expected in checks.items():
        path = directory / name
        if Path(name).name != name or path.is_symlink() or not path.is_file():
            raise ValueError('Unsafe or missing snapshot file')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Snapshot checksum mismatch: {name}')
    if not {'deployment.json', 'service.json', 'links.json'} <= set(checks):
        raise ValueError('Incomplete app snapshot')


def snapshot(prefix='app-snapshot.'):
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=STATE))
    (directory / 'deployment.json').write_text(json.dumps(owned_deployment(resource('deployment', 'home-portal')), indent=2))
    (directory / 'service.json').write_text(json.dumps(resource('service', 'home-portal'), indent=2))
    shutil.copyfile(CONFIG, directory / 'links.json')
    if RELEASE.exists():
        subprocess.run(['sha256sum', '--check', str(RELEASE) + '.sha256'], check=True, capture_output=True)
        shutil.copyfile(RELEASE, directory / 'release.json')
    for path in directory.iterdir():
        path.chmod(0o600)
    seal(directory)
    print(f'Verified private snapshot: {directory}', flush=True)
    return directory


def restore(directory):
    verify(directory)
    deployment = owned_deployment(json.loads((directory / 'deployment.json').read_text()))
    owned_deployment(resource('deployment', 'home-portal'))
    if not (directory / 'release.json').exists():
        raise ValueError('Only registry-release snapshots support automated rollback')
    release = load_release(directory / 'release.json')
    image = deployment['spec']['template']['spec']['containers'][0]['image']
    if release['image'] != image:
        raise ValueError('Saved release does not match the saved Deployment image')
    saved_service = json.loads((directory / 'service.json').read_text())
    if resource('service', 'home-portal')['spec'] != saved_service['spec']:
        raise ValueError('Service has drifted; inspect it before restoring this snapshot')
    subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'app/server.py'),
                    '--check-config', str(directory / 'links.json')], check=True, capture_output=True, timeout=10)
    config_name = deployment['spec']['template']['spec']['volumes'][0]['configMap']['name']
    config_map = resource('configmap', config_name)
    if not config_map.get('immutable') or config_map['data']['links.json'] != (directory / 'links.json').read_text():
        raise ValueError('Saved immutable ConfigMap is missing or does not match the saved links')
    # Only this Deployment's spec is restored; server metadata/status are not replayed.
    print(kubectl('patch', 'deployment', 'home-portal', '--type=json', '-p',
                  json.dumps([{'op': 'replace', 'path': '/spec', 'value': deployment['spec']}])), end='', flush=True)
    print(kubectl('rollout', 'status', 'deployment/home-portal', '--timeout=180s'), end='', flush=True)
    expected = release['revision']
    pods = json.loads(kubectl('get', 'pods', '-l', 'app=home-portal', '-o', 'json'))
    subprocess.run([sys.executable, str(Path(__file__).with_name('check-replicas.py')), expected, image],
                   input=json.dumps(pods), text=True, check=True, timeout=20)
    subprocess.run(['bash', str(Path(__file__).with_name('check-app.sh'))], check=True, timeout=100)
    # Activate the restored local configuration only after runtime checks pass.
    shutil.copyfile(directory / 'links.json', CONFIG)
    CONFIG.chmod(0o600)
    if (directory / 'release.json').exists():
        shutil.copyfile(directory / 'release.json', RELEASE)
        RELEASE.chmod(0o600)
        checksum = hashlib.sha256(RELEASE.read_bytes()).hexdigest()
        Path(str(RELEASE) + '.sha256').write_text(f'{checksum}  {RELEASE}\n')


def main():
    if sys.argv[1:] == ['--snapshot-held-lock']:
        # deploy-app.sh already owns this lock; its child inherits the same fd.
        if os.geteuid() != 0 or os.readlink('/proc/self/fd/9') != '/run/lock/pi-k3s-lab-app.lock':
            raise RuntimeError('Expected the root deployment lock on fd 9')
        fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot()
        return
    if sys.argv[1:] == ['--snapshot']:
        with app_lock():
            snapshot()
        return
    directory = Path(sys.argv[1])
    if (directory.is_symlink() or directory.resolve().parent != STATE or not directory.name.startswith('app-snapshot.')
            or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o022):
        raise ValueError('Select a root-owned app-snapshot directory under the lab state path')
    with app_lock():
        verify(directory)
        safety = snapshot()
        print(f'Rollback safety snapshot: {safety}', flush=True)
        restore(directory)
        print('PASS: restored portal snapshot and checked both replicas', flush=True)


if __name__ == '__main__':
    main()
