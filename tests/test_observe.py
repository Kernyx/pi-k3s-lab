import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import dashboard


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


discovery = module('discovery_test', 'discover-portal.py')
load = module('load_test', 'load-portal.py')
observer = module('observer_test', 'observe.py')


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.document = {'items': [{'metadata': {'namespace': 'homelab', 'labels': {'kubernetes.io/service-name': 'home-portal'}},
                                   'ports': [{'name': 'http', 'port': 8080, 'protocol': 'TCP'}],
                                   'endpoints': [{'addresses': ['10.42.0.25'], 'conditions': {'ready': True},
                                                  'targetRef': {'kind': 'Pod', 'namespace': 'homelab', 'name': 'pod-a'}}]}]}

    def test_ready_pod_labels_and_empty_success(self):
        result = discovery.targets(self.document)
        self.assertEqual(result[0]['targets'], ['10.42.0.25:8080'])
        self.assertEqual(result[0]['labels']['instance'], 'pod-a')
        self.assertEqual(discovery.targets({'items': []}), [])

    def test_unready_and_terminating_excluded(self):
        for conditions in ({'ready': False}, {'ready': True, 'terminating': True}, {}):
            self.document['items'][0]['endpoints'][0]['conditions'] = conditions
            self.assertEqual(discovery.targets(self.document), [])

    def test_refuses_foreign_owner_network_or_port(self):
        for change in ('owner', 'address', 'port'):
            data = copy.deepcopy(self.document)
            if change == 'owner':
                data['items'][0]['metadata']['namespace'] = 'other'
            elif change == 'address':
                data['items'][0]['endpoints'][0]['addresses'] = ['203.0.113.1']
            else:
                data['items'][0]['ports'][0]['port'] = 80
            with self.assertRaises(ValueError):
                discovery.targets(data)

    def test_atomic_write_skips_unchanged_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'targets.json'
            discovery.atomic_write(path, b'[]\n')
            previous = path.stat().st_mtime_ns
            discovery.atomic_write(path, b'[]\n')
            self.assertEqual(path.stat().st_mtime_ns, previous)
            discovery.atomic_write(path, b'[{}]\n')
            self.assertEqual(path.read_bytes(), b'[{}]\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(len(list(path.parent.iterdir())), 1)


class DashboardAndLoadTest(unittest.TestCase):
    def test_dashboard_has_stable_uid_and_existing_datasource(self):
        data = dashboard.dashboard()
        json.dumps(data)
        self.assertEqual(data['uid'], 'pi-k3s-home-portal')
        self.assertEqual(len(data['panels']), 8)
        self.assertTrue(all(p['datasource']['uid'] == 'prometheus' for p in data['panels']))
        self.assertTrue(all('home-portal' in p['targets'][0]['expr'] for p in data['panels']))

    def test_load_summary_counts_failed_samples(self):
        data = [{'ok': True, 'instance': 'pod-a', 'latency_ms': i} for i in range(1, 20)]
        data.append({'ok': False, 'instance': None, 'latency_ms': 20})
        result = load.summarize(data, 2)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['client_p95_ms'], 19)
        self.assertEqual(result['actual_rps'], 10)
        self.assertEqual(result['instances'], ['pod-a'])


class ObserveBackupTest(unittest.TestCase):
    def test_external_scrape_job_is_not_in_main_config_api(self):
        config = 'scrape_config_files:\n- /etc/prometheus/pi-k3s-lab/home-portal.yml\nscrape_configs:\n- job_name: node\n'
        self.assertNotIn('job_name: home-portal', config)
        self.assertTrue(observer.reload_active(config, ['node', 'home-portal'], True))
        self.assertFalse(observer.reload_active(config, ['node'], True))

    def test_undo_checks_pool_and_include_disappearance(self):
        self.assertTrue(observer.reload_active('scrape_configs: []', ['node'], False))
        self.assertFalse(observer.reload_active('scrape_configs: []', ['node', 'home-portal'], False))

    def test_private_backup_inventory_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            config = state / 'prometheus.yml'
            config.write_text('global: {}\n')
            missing = state / 'missing'
            with patch.object(observer, 'STATE', state), patch.object(observer, 'FILES', [config, missing]), \
                    patch.object(observer, 'subprocess') as process:
                process.run.return_value.stdout = 'disabled'
                # The verifier checks real file ownership; ordinary unit tests don't run as root.
                original_stat = Path.stat
                def root_stat(path, *args, **kwargs):
                    stat = original_stat(path, *args, **kwargs)
                    values = list(stat)
                    values[4] = 0
                    return os.stat_result(values)
                with patch.object(Path, 'stat', root_stat):
                    saved = observer.backup()
                    manifest = observer.verify(saved)
                    self.assertIsNone(manifest['files'][str(missing)])
                    self.assertEqual((saved / '0').stat().st_mode & 0o777, 0o600)
                    (saved / '0').write_text('tampered')
                    with self.assertRaises(ValueError):
                        observer.verify(saved)
