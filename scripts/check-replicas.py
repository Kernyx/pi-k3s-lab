#!/usr/bin/env python3
"""Verify the image and actual HTTP version of both non-terminating replicas."""

import json
import sys
from urllib.request import urlopen

pods = [pod for pod in json.load(sys.stdin)["items"] if not pod["metadata"].get("deletionTimestamp")]
if len(pods) != 2:
    raise SystemExit("Expected exactly two active portal replicas")
for pod in pods:
    ready = any(c["type"] == "Ready" and c["status"] == "True" for c in pod["status"].get("conditions", []))
    if not ready or pod["spec"]["containers"][0]["image"] != sys.argv[2]:
        raise SystemExit("Replica is not ready or uses an unexpected image")
    with urlopen(f"http://{pod['status']['podIP']}:8080/api/info", timeout=5) as response:
        info = json.load(response)
    if info["version"] != sys.argv[1] or info["instance"] != pod["metadata"]["name"]:
        raise SystemExit("Runtime version/instance does not match the selected release")
    print(info["instance"], info["version"])
