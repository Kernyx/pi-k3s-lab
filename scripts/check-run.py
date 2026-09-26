#!/usr/bin/env python3
"""Only accept a successful main-branch push from the selected repository."""

import json
import re
import sys

run = json.load(sys.stdin)
if (run.get("conclusion") != "success" or run.get("event") != "push"
        or run.get("headBranch") != "main" or not re.fullmatch(r"[0-9a-f]{40}", run.get("headSha", ""))):
    raise SystemExit("Expected a successful main push workflow with a full commit SHA")
print(run["headSha"])
