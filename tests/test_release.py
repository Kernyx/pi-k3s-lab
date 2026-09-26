import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "release.json"
        self.data = {"image": "ghcr.io/example/pi-k3s-lab@sha256:" + "a" * 64, "revision": "b" * 40}
        self.inspection = {"status": {"repoDigests": [self.data["image"]]}, "info": {"imageSpec": {
            "architecture": "arm64", "os": "linux", "config": {
                "Labels": {"org.opencontainers.image.source": "https://github.com/Example/pi-k3s-lab",
                           "org.opencontainers.image.revision": self.data["revision"]},
                "Env": ["APP_VERSION=" + self.data["revision"]]}}}}

    def write(self, data):
        self.path.write_text(json.dumps(data))

    def test_accepts_digest_and_full_revision(self):
        self.write(self.data)
        self.assertEqual(release.load_release(self.path), self.data)

    def test_rejects_tags_unexpected_registries_and_shell_input(self):
        for image in ["ghcr.io/example/pi-k3s-lab:latest", "docker.io/example/pi-k3s-lab@sha256:" + "a" * 64,
                      self.data["image"] + "; echo unsafe", self.data["image"][:-1]]:
            with self.subTest(image=image):
                self.write({**self.data, "image": image})
                with self.assertRaises(ValueError):
                    release.load_release(self.path)

    def test_rejects_invalid_schema_or_revision(self):
        for data in [[], {**self.data, "token": "not-allowed"}, {**self.data, "revision": "short"},
                     {**self.data, "revision": None}]:
            with self.subTest(data=data):
                self.write(data)
                with self.assertRaises(ValueError):
                    release.load_release(self.path)

    def test_rejects_oversized_descriptor(self):
        self.path.write_text(" " * 4097)
        with self.assertRaises(ValueError):
            release.load_release(self.path)

    def test_accepts_matching_image_metadata(self):
        release.check_image(self.data, self.inspection)

    def test_rejects_wrong_platform_digest_source_revision_or_version(self):
        for field in ["architecture", "os", "digest", "source", "revision", "version"]:
            with self.subTest(field=field):
                inspection = copy.deepcopy(self.inspection)
                image = inspection["info"]["imageSpec"]
                if field in {"architecture", "os"}:
                    image[field] = "wrong"
                elif field == "digest":
                    inspection["status"]["repoDigests"] = []
                elif field == "version":
                    image["config"]["Env"] = ["APP_VERSION=wrong"]
                else:
                    image["config"]["Labels"]["org.opencontainers.image." + field] = "wrong"
                with self.assertRaises(ValueError):
                    release.check_image(self.data, inspection)
