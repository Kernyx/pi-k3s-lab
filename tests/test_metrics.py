from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import time
import unittest
import test_portal
from urllib.request import Request, urlopen

portal = test_portal.portal


class MetricsTest(unittest.TestCase):
    def render(self, metrics):
        server = SimpleNamespace(config={}, started=time.monotonic(), version='test"\\\n')
        return metrics.render(server).decode()

    def test_histogram_cumulative_and_count(self):
        metrics = portal.Metrics()
        for duration in (0.001, 0.003, 10):
            metrics.observe("/", "GET", 200, duration)
        text = self.render(metrics)
        self.assertIn('bucket{le="0.001"} 1', text)
        self.assertIn('bucket{le="0.005"} 2', text)
        self.assertIn('bucket{le="+Inf"} 3', text)
        self.assertIn('duration_seconds_count 3', text)
        self.assertIn('duration_seconds_sum 10.004000000', text)
        self.assertTrue(text.endswith("\n"))

    def test_labels_are_bounded_and_probes_excluded(self):
        metrics = portal.Metrics()
        for path in metrics.excluded:
            metrics.observe(path, "GET", 200, 1)
        for i in range(1000):
            metrics.observe(f"/private/{i}", "DELETE", 501, 0.01)
        self.assertEqual(metrics.count, 1000)
        self.assertEqual(len(metrics.requests), 1)
        self.assertNotIn("/private", self.render(metrics))

    def test_thread_safe_updates(self):
        metrics = portal.Metrics()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: metrics.observe("/", "GET", 200, 0.001), range(2000)))
        self.assertEqual(metrics.count, 2000)
        self.assertEqual(metrics.buckets, [2000 * int(0.001 <= bound) for bound in metrics.bounds])

    def test_build_label_escaping(self):
        self.assertIn('version="test\\"\\\\\\n"', self.render(portal.Metrics()))


class MetricsHTTPTest(unittest.TestCase):
    setUp = test_portal.PortalTest.setUp
    start_server = test_portal.PortalTest.start_server

    def test_metrics_get_head_and_query_privacy(self):
        base = self.start_server()
        with urlopen(base + "/api/info?secret=not-a-label", timeout=2) as response:
            response.read()
        with urlopen(base + "/metrics", timeout=2) as response:
            text = response.read().decode()
            self.assertIn("version=0.0.4", response.headers["Content-Type"])
            self.assertIn('route="/api/info",method="GET",status="200"} 1', text)
            self.assertNotIn("secret", text)
            self.assertIn("portal_ready 1", text)
        with urlopen(Request(base + "/metrics", method="HEAD"), timeout=2) as response:
            self.assertEqual(response.read(), b"")

    def test_invalid_config_readiness_metric(self):
        self.config.write_text("invalid")
        base = self.start_server()
        with urlopen(base + "/metrics", timeout=2) as response:
            self.assertIn(b"portal_ready 0", response.read())
