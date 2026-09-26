import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import app_state

spec = importlib.util.spec_from_file_location('drill', SCRIPTS / 'rollout-drill.py')
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        for name in ['deployment.json', 'service.json', 'links.json']:
            (self.path / name).write_text('{}')

    def test_seal_verifies_and_rejects_modified_file(self):
        app_state.seal(self.path)
        app_state.verify(self.path)
        (self.path / 'deployment.json').write_text('{"modified":true}')
        with self.assertRaises(ValueError):
            app_state.verify(self.path)

    def test_rejects_incomplete_snapshot(self):
        (self.path / 'links.json').unlink()
        with self.assertRaises(ValueError):
            app_state.seal(self.path)

    def test_rejects_symlinks_and_path_traversal(self):
        app_state.seal(self.path)
        (self.path / 'links.json').unlink()
        (self.path / 'links.json').symlink_to(self.path / 'service.json')
        with self.assertRaises(ValueError):
            app_state.verify(self.path)
        (self.path / 'checksums.json').write_text(json.dumps({'../escape': 'bad'}))
        with self.assertRaises(ValueError):
            app_state.verify(self.path)

    def test_rejects_unowned_deployment(self):
        for metadata in [{}, {'name': 'other', 'namespace': 'homelab'},
                         {'name': 'home-portal', 'namespace': 'default'}]:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                app_state.owned_deployment({'metadata': metadata})


class SummaryTest(unittest.TestCase):
    def test_counts_http_and_transport_errors_without_retry_masking(self):
        data = [{'status': 200, 'latency_ms': i, 'instance': 'pod-a', 'version': 'release-a'} for i in range(1, 19)]
        data += [{'status': 503, 'latency_ms': 19}, {'status': 0, 'latency_ms': 20}]
        result = drill.summarize(data)
        self.assertEqual(result['requests'], 20)
        self.assertEqual(result['errors'], 2)
        self.assertEqual(result['latency_p95_ms'], 19)
        self.assertEqual(result['instances'], ['pod-a'])

    def test_empty_summary_does_not_invent_latency(self):
        result = drill.summarize([])
        self.assertEqual(result['requests'], 0)
        self.assertIsNone(result['latency_p95_ms'])
