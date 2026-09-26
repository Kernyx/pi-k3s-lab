import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

spec = importlib.util.spec_from_file_location("portal", Path(__file__).resolve().parents[1] / "app/server.py")
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


class PortalTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name) / "links.json"
        self.data = {"title": "Home lab", "links": [{"name": "Docs", "url": "https://example.com"}]}
        self.config.write_text(json.dumps(self.data))

    def start_server(self):
        server = portal.PortalServer(("127.0.0.1", 0), self.config, "test-release", "test-pod")
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        def stop():
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_valid_configuration(self):
        self.assertEqual(portal.load_config(self.config)["links"][0]["description"], "")

    def test_rejects_unsafe_links(self):
        for url in ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.com",
                    "https://example.com:99999", "https://example.com/\n", "//example.com"]:
            with self.subTest(url=url):
                self.data["links"][0]["url"] = url
                self.config.write_text(json.dumps(self.data))
                with self.assertRaises(ValueError):
                    portal.load_config(self.config)

    def test_rejects_invalid_structure(self):
        for data in [[], {"title": "", "links": []}, {"title": "Lab", "links": ["bad"]}]:
            with self.subTest(data=data):
                self.config.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    portal.load_config(self.config)

    def test_serves_config_version_and_assets(self):
        base = self.start_server()
        for path in ["/healthz", "/readyz", "/", "/style.css", "/app.js"]:
            with self.subTest(path=path), urlopen(base + path, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertGreater(len(response.read()), 0)
        with urlopen(base + "/api/config", timeout=2) as response:
            self.assertEqual(json.load(response)["title"], "Home lab")
        with urlopen(base + "/api/info", timeout=2) as response:
            self.assertEqual(json.load(response)["version"], "test-release")

    def test_liveness_does_not_depend_on_valid_config(self):
        self.config.write_text("invalid json")
        base = self.start_server()
        with urlopen(base + "/healthz", timeout=2) as response:
            self.assertEqual(response.status, 200)
        for path in ["/readyz", "/api/config"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(base + path, timeout=2)
            self.assertEqual(error.exception.code, 503)
            error.exception.close()

    def test_unknown_path_does_not_serve_arbitrary_files(self):
        base = self.start_server()
        with self.assertRaises(HTTPError) as error:
            urlopen(base + "/server.py", timeout=2)
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
