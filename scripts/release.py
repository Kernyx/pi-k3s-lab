#!/usr/bin/env python3
"""Validate a public release descriptor and its downloaded OCI image metadata."""

import json
from pathlib import Path
import re
import sys


def load_release(path):
    path = Path(path)
    if path.stat().st_size > 4096:
        raise ValueError("Release descriptor is too large")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"image", "revision"}:
        raise ValueError("Expected image and revision only")
    if not isinstance(data["image"], str) or not re.fullmatch(
        r"ghcr\.io/[a-z0-9][a-z0-9._-]*/pi-k3s-lab@sha256:[0-9a-f]{64}", data["image"]
    ):
        raise ValueError("Expected a GHCR lab image pinned by SHA-256 digest")
    if not isinstance(data["revision"], str) or not re.fullmatch(r"[0-9a-f]{40}", data["revision"]):
        raise ValueError("Expected a full Git commit SHA")
    return data


def check_image(release, inspection):
    image = inspection["info"]["imageSpec"]
    config = image["config"]
    labels = config.get("Labels", {})
    owner = release["image"].split("/")[1]
    if image.get("architecture") != "arm64" or image.get("os") != "linux":
        raise ValueError("Expected a Linux ARM64 image")
    if labels.get("org.opencontainers.image.source", "").lower() != f"https://github.com/{owner}/pi-k3s-lab":
        raise ValueError("Image source does not match the lab repository")
    if labels.get("org.opencontainers.image.revision") != release["revision"]:
        raise ValueError("Image revision does not match the release descriptor")
    if f"APP_VERSION={release['revision']}" not in config.get("Env", []):
        raise ValueError("Application version does not match the release descriptor")
    if release["image"] not in inspection["status"].get("repoDigests", []):
        raise ValueError("Downloaded image digest does not match the release descriptor")


if __name__ == "__main__":
    release = load_release(sys.argv[1])
    if len(sys.argv) == 3:
        check_image(release, json.loads(Path(sys.argv[2]).read_text()))
    print(release["image"])
    print(release["revision"])
